"""Local read/write operations console for SOC Agent."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from soc_agent.queue_backend import create_queue_store


class ConsoleState:
    def __init__(
        self,
        project_root,
        reports_dir,
        queue_db,
        command_factory=None,
        upload_command_factory=None,
        max_upload_bytes=10 * 1024 * 1024,
    ):
        self.project_root = Path(project_root).expanduser().resolve()
        self.reports_dir = Path(reports_dir).expanduser().resolve()
        self.queue_db = str(queue_db)
        self.command_factory = command_factory or self._default_command
        self.upload_command_factory = (
            upload_command_factory or self._default_upload_command
        )
        self.max_upload_bytes = max_upload_bytes
        self._process = None
        self._log_file = None
        self._output_dir = None
        self._started_at = None
        self._run_meta = {}
        self._lock = threading.Lock()

    def overview(self):
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        reports = []
        files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[:50]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = (
                payload.get("dataset_name")
                or payload.get("workflow_name")
                or payload.get("task_name")
                or path.stem
            )
            report_type = (
                "dataset"
                if payload.get("dataset_name")
                else (
                    "workflow"
                    if payload.get("workflow_name")
                    else "task"
                )
            )
            reports.append(
                {
                    "name": name,
                    "type": report_type,
                    "status": payload.get("status", "unknown"),
                    "duration_seconds": payload.get(
                        "duration_seconds"
                    ),
                    "updated_at": path.stat().st_mtime,
                    "url": "/files/" + path.relative_to(
                        self.reports_dir
                    ).as_posix(),
                }
            )

        workers = []
        try:
            store = create_queue_store(self.queue_db)
            workers = [
                {
                    "worker_id": worker.worker_id,
                    "hostname": worker.hostname,
                    "pid": worker.pid,
                    "state": worker.state.value,
                    "current_job_id": worker.current_job_id,
                    "last_heartbeat": worker.last_heartbeat.isoformat(),
                    "labels": worker.labels,
                }
                for worker in store.list_workers(
                    online_within_seconds=600
                )
            ]
        except Exception as error:
            worker_error = str(error)
        else:
            worker_error = None

        return {
            "reports": reports,
            "workers": workers,
            "worker_error": worker_error,
            "demo": self.demo_status(),
            "history": self.history(),
        }

    def start_invoice_demo(self):
        with self._lock:
            return self._start_run(
                kind="demo",
                command_factory=self.command_factory,
            )

    def start_uploaded_input(
        self,
        filename: str,
        content: bytes,
    ):
        safe_name = Path(filename).name
        suffix = Path(safe_name).suffix.casefold()
        if suffix not in {".csv", ".xlsx", ".xlsm", ".pdf"}:
            return {
                "started": False,
                "error": "only CSV, XLSX, XLSM, and PDF inputs are supported",
            }
        if not content:
            return {"started": False, "error": "uploaded file is empty"}
        if len(content) > self.max_upload_bytes:
            return {
                "started": False,
                "error": "uploaded file exceeds the 10 MB limit",
            }
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return {"started": False, "error": "a run is already active"}
            timestamp = datetime.now(timezone.utc).strftime(
                "%Y%m%d-%H%M%S-%f"
            )
            output_dir = self.reports_dir / f"console-upload-{timestamp}"
            output_dir.mkdir(parents=True, exist_ok=True)
            input_path = output_dir / f"input{suffix}"
            input_path.write_bytes(content)
            return self._start_run(
                kind="upload",
                command_factory=lambda run_dir: self.upload_command_factory(
                    run_dir,
                    input_path,
                ),
                output_dir=output_dir,
                source_name=safe_name,
            )

    def cancel_active_run(self):
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return {"cancelled": False, "error": "no active run"}

            self._run_meta["state"] = "cancelling"
            self._run_meta["cancel_requested"] = True
            self._write_run_metadata()
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=5)
            except ProcessLookupError:
                pass

            exit_code = process.poll()
            self._run_meta["state"] = "cancelled"
            self._run_meta["exit_code"] = exit_code
            self._run_meta["finished_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            self._write_run_metadata()
            return {
                "cancelled": True,
                "exit_code": exit_code,
                "state": "cancelled",
            }

    def _start_run(
        self,
        kind,
        command_factory,
        output_dir=None,
        source_name=None,
    ):
        if self._process is not None and self._process.poll() is None:
            return {"started": False, "error": "a run is already active"}
        if self._log_file is not None:
            self._log_file.close()
        if output_dir is None:
            timestamp = datetime.now(timezone.utc).strftime(
                "%Y%m%d-%H%M%S-%f"
            )
            output_dir = self.reports_dir / f"console-{kind}-{timestamp}"
            output_dir.mkdir(parents=True, exist_ok=True)
        command = command_factory(output_dir)
        log_path = output_dir / "run.log"
        log_file = log_path.open("w", encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONUNBUFFERED"] = "1"
        self._process = subprocess.Popen(
            command,
            cwd=self.project_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
            start_new_session=(os.name == "posix"),
        )
        self._log_file = log_file
        self._output_dir = output_dir
        self._started_at = time.time()
        self._run_meta = {
            "kind": kind,
            "source_name": source_name,
            "state": "running",
            "cancel_requested": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
        }
        self._write_run_metadata()
        return {
            "started": True,
            "kind": kind,
            "output_dir": str(output_dir),
        }

    def demo_status(self):
        if self._process is None:
            return {"state": "idle", "history": self.history()}
        exit_code = self._process.poll()
        if exit_code is None:
            state = "running"
        elif self._run_meta.get("cancel_requested"):
            state = "cancelled"
        else:
            state = "finished"
        if self._run_meta.get("state") != state:
            self._run_meta["state"] = state
            self._run_meta["exit_code"] = exit_code
            self._run_meta["finished_at"] = (
                datetime.now(timezone.utc).isoformat()
                if exit_code is not None
                else None
            )
            self._write_run_metadata()
        return {
            "state": state,
            "exit_code": exit_code,
            "started_at": self._started_at,
            "elapsed_seconds": (
                time.time() - self._started_at
                if self._started_at is not None
                else None
            ),
            "output_dir": (
                str(self._output_dir) if self._output_dir else None
            ),
            "kind": self._run_meta.get("kind"),
            "source_name": self._run_meta.get("source_name"),
            "log_tail": self._read_log_tail(),
            "artifacts": self._artifact_links(),
            "history": self.history(),
        }

    def history(self):
        entries = []
        for run_json in sorted(
            self.reports_dir.glob("console-*/run.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:20]:
            try:
                payload = json.loads(
                    run_json.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
            output_dir = run_json.parent
            payload["run_url"] = (
                "/files/"
                + run_json.relative_to(self.reports_dir).as_posix()
            )
            payload["artifacts"] = self._artifact_links(output_dir)
            entries.append(payload)
        return entries

    def _default_command(self, output_dir: Path):
        return [
            sys.executable,
            "-m",
            "soc_agent",
            "scenario",
            "run",
            "scenarios/invoice_reconciliation/scenario.json",
            "--non-interactive",
            "--reset-checkpoint",
            "--failure-config",
            "scenarios/invoice_reconciliation/failure-example.json",
            "--checkpoint",
            str(output_dir / "checkpoint.json"),
            "--screenshot-dir",
            str(output_dir / "evidence"),
            "--output",
            str(output_dir / "reconciliation.json"),
            "--html",
            str(output_dir / "reconciliation.html"),
            "--xlsx",
            str(output_dir / "reconciliation.xlsx"),
        ]

    def _default_upload_command(
        self,
        output_dir: Path,
        input_path: Path,
    ):
        scenario_dir = (
            self.project_root / "scenarios" / "invoice_reconciliation"
        )
        return [
            sys.executable,
            "-m",
            "soc_agent",
            "erp-reconcile",
            str(input_path),
            "--enterprise",
            "--mock-erp-data",
            str(scenario_dir / "data" / "erp_invoices.json"),
            "--selector-profile",
            str(scenario_dir / "selectors.json"),
            "--config",
            str(scenario_dir / "mapping.json"),
            "--checkpoint",
            str(output_dir / "checkpoint.json"),
            "--screenshot-dir",
            str(output_dir / "evidence"),
            "--output",
            str(output_dir / "reconciliation.json"),
            "--html",
            str(output_dir / "reconciliation.html"),
            "--xlsx",
            str(output_dir / "reconciliation.xlsx"),
        ]

    def _write_run_metadata(self):
        if self._output_dir is None:
            return
        path = self._output_dir / "run.json"
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(
                self._run_meta,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _read_log_tail(self, lines=60):
        if self._output_dir is None:
            return []
        log_path = self._output_dir / "run.log"
        if not log_path.is_file():
            return []
        try:
            return log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()[-lines:]
        except OSError:
            return []

    def _artifact_links(self, output_dir=None):
        root = output_dir or self._output_dir
        if root is None:
            return []
        artifacts = []
        for name in (
            "reconciliation.json",
            "reconciliation.html",
            "reconciliation.xlsx",
            "checkpoint.json",
            "run.log",
            "run.json",
        ):
            path = root / name
            if path.is_file():
                artifacts.append(
                    {
                        "name": name,
                        "url": "/files/"
                        + path.relative_to(
                            self.reports_dir
                        ).as_posix(),
                    }
                )
        return artifacts

    def resolve_file(self, relative_path: str) -> Optional[Path]:
        candidate = (
            self.reports_dir / unquote(relative_path)
        ).resolve()
        try:
            candidate.relative_to(self.reports_dir)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None


class ConsoleServer(ThreadingHTTPServer):
    def __init__(self, address, state: ConsoleState):
        super().__init__(address, ConsoleHandler)
        self.state = state


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_console_html())
            return
        if parsed.path == "/api/overview":
            self._send_json(self.server.state.overview())
            return
        if parsed.path == "/api/demo/status":
            self._send_json(self.server.state.demo_status())
            return
        if parsed.path.startswith("/files/"):
            path = self.server.state.resolve_file(
                parsed.path[len("/files/"):]
            )
            if path is None:
                self._send_json(
                    {"error": "file not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_file(path)
            return
        self._send_json(
            {"error": "not found"},
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/demo/run":
            payload = self.server.state.start_invoice_demo()
            self._send_json(
                payload,
                status=(
                    HTTPStatus.ACCEPTED
                    if payload.get("started")
                    else HTTPStatus.CONFLICT
                ),
            )
            return
        if parsed.path == "/api/demo/cancel":
            payload = self.server.state.cancel_active_run()
            self._send_json(
                payload,
                status=(
                    HTTPStatus.OK
                    if payload.get("cancelled")
                    else HTTPStatus.CONFLICT
                ),
            )
            return
        if parsed.path == "/api/upload/run":
            query = parsed.query
            filename = ""
            for part in query.split("&"):
                if part.startswith("filename="):
                    filename = unquote(part[len("filename="):])
                    break
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length > self.server.state.max_upload_bytes:
                self._send_json(
                    {"started": False, "error": "upload exceeds 10 MB"},
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return
            content = self.rfile.read(length)
            payload = self.server.state.start_uploaded_input(
                filename,
                content,
            )
            if payload.get("started"):
                status = HTTPStatus.ACCEPTED
            elif "already active" in payload.get("error", ""):
                status = HTTPStatus.CONFLICT
            else:
                status = HTTPStatus.BAD_REQUEST
            self._send_json(payload, status=status)
            return
        self._send_json(
            {"error": "not found"},
            status=HTTPStatus.NOT_FOUND,
        )

    def _send_file(self, path: Path):
        content = path.read_bytes()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".xlsx": (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            ".png": "image/png",
            ".log": "text/plain; charset=utf-8",
        }.get(path.suffix.casefold(), "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_html(self, html):
        content = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload, status=HTTPStatus.OK):
        content = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        return


def create_console_server(
    project_root,
    reports_dir="reports",
    queue_db="reports/queue.db",
    host="127.0.0.1",
    port=0,
    command_factory=None,
    upload_command_factory=None,
    max_upload_bytes=10 * 1024 * 1024,
):
    state = ConsoleState(
        project_root,
        reports_dir,
        queue_db,
        command_factory=command_factory,
        upload_command_factory=upload_command_factory,
        max_upload_bytes=max_upload_bytes,
    )
    return ConsoleServer((host, port), state)


def _console_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SOC Agent Console</title>
  <style>
    body { font-family:-apple-system,BlinkMacSystemFont,sans-serif;
      background:#f4f6f8; color:#17202a; margin:0; }
    main { max-width:1100px; margin:36px auto; padding:0 24px; }
    .bar { display:flex; gap:12px; align-items:center; }
    .bar input { padding:8px; }
    button { border:0; border-radius:8px; padding:10px 16px;
      background:#1463ff; color:white; cursor:pointer; }
    section { background:white; border-radius:12px; padding:18px;
      margin:18px 0; box-shadow:0 8px 24px #17202a12; }
    table { width:100%; border-collapse:collapse; }
    th,td { text-align:left; padding:10px; border-bottom:1px solid #e2e7ec; }
    .muted { color:#65717c; } a { color:#1463ff; }
    .status-passed { color:#16834b; font-weight:600; }
    .status-failed { color:#c53727; font-weight:600; }
    pre { background:#111820; color:#d9e6ef; padding:14px;
      border-radius:10px; max-height:240px; overflow:auto; }
  </style>
</head>
<body>
  <main>
    <div class="bar">
      <h1>SOC Agent Console</h1>
      <button id="run-demo">运行发票对账 Demo</button>
      <button id="cancel-run" style="background:#c53727">停止当前运行</button>
      <input id="upload-file" type="file"
        accept=".csv,.xlsx,.xlsm,.pdf">
      <button id="run-upload">上传并运行</button>
    </div>
    <div id="demo-status" class="muted">Demo idle</div>
    <section>
      <h2>当前运行</h2>
      <div id="run-details" class="muted">No active run.</div>
      <div id="artifacts"></div>
      <pre id="run-log" hidden></pre>
    </section>
    <section>
      <h2>在线 Worker</h2>
      <div id="workers" class="muted">Loading...</div>
    </section>
    <section>
      <h2>运行历史</h2>
      <div id="history" class="muted">No runs yet.</div>
    </section>
    <section>
      <h2>最近报告</h2>
      <table>
        <thead><tr><th>名称</th><th>类型</th><th>状态</th>
        <th>耗时</th><th>报告</th></tr></thead>
        <tbody id="reports"></tbody>
      </table>
    </section>
  </main>
  <script>
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
      }[char]));
    }
    function artifactLinks(artifacts) {
      return (artifacts || []).map(item =>
        `<a href="${item.url}" target="_blank">${escapeHtml(item.name)}</a>`
      ).join(" · ");
    }
    async function refresh() {
      const response = await fetch("/api/overview");
      const payload = await response.json();
      document.getElementById("workers").innerHTML =
        payload.workers.length
          ? payload.workers.map(worker =>
              `<div><strong>${escapeHtml(worker.worker_id)}</strong>
               ${escapeHtml(worker.state)}
               ${escapeHtml(worker.hostname)}:${worker.pid}
               ${escapeHtml((worker.labels || []).join(","))}</div>`
            ).join("")
          : "No online Workers.";
      const rows = payload.reports.map((report) => {
        const duration = report.duration_seconds == null ? "-" :
          Number(report.duration_seconds).toFixed(2) + "s";
        return `<tr><td>${report.name}</td><td>${report.type}</td>
          <td class="status-${report.status}">${report.status}</td>
          <td>${duration}</td><td><a href="${report.url}">打开</a></td></tr>`;
      });
      document.getElementById("reports").innerHTML = rows.join("");
      const run = payload.demo;
      const elapsed = run.elapsed_seconds == null ? "" :
        Number(run.elapsed_seconds).toFixed(1) + "s";
      document.getElementById("demo-status").textContent =
        "Run " + run.state +
        (run.exit_code == null ? "" : " (exit " + run.exit_code + ")") +
        (elapsed ? " · " + elapsed : "");
      document.getElementById("run-details").textContent =
        run.state === "idle" ? "No active run." :
        `${run.kind || "demo"} · ${run.source_name || "built-in data"} · ${run.state}`;
      document.getElementById("artifacts").innerHTML =
        artifactLinks(run.artifacts);
      const log = document.getElementById("run-log");
      if (run.log_tail && run.log_tail.length) {
        log.hidden = false;
        log.textContent = run.log_tail.join("\\n");
        log.scrollTop = log.scrollHeight;
      } else {
        log.hidden = true;
      }
      const history = payload.history || [];
      document.getElementById("history").innerHTML =
        history.length
          ? history.map(item =>
              `<div><strong>${escapeHtml(item.kind || "run")}</strong>
               ${escapeHtml(item.state || "unknown")}
               ${escapeHtml(item.source_name || "")}
               ${new Date((item.started_at || 0)).toLocaleString()}
               ${artifactLinks(item.artifacts)}</div>`
            ).join("")
          : "No runs yet.";
    }
    document.getElementById("run-demo").addEventListener(
      "click", async () => {
        const response = await fetch("/api/demo/run", {method:"POST"});
        const payload = await response.json();
        if (!response.ok) alert(payload.error || "启动失败");
        refresh();
      }
    );
    document.getElementById("cancel-run").addEventListener(
      "click", async () => {
        const response = await fetch("/api/demo/cancel", {method:"POST"});
        const payload = await response.json();
        if (!response.ok && payload.error !== "no active run") {
          alert(payload.error || "停止失败");
        }
        refresh();
      }
    );
    document.getElementById("run-upload").addEventListener(
      "click", async () => {
        const file = document.getElementById("upload-file").files[0];
        if (!file) {
          alert("请选择 CSV、XLSX 或 PDF 文件");
          return;
        }
        const response = await fetch(
          "/api/upload/run?filename=" + encodeURIComponent(file.name),
          {method:"POST", body:file}
        );
        const payload = await response.json();
        if (!response.ok) alert(payload.error || "启动失败");
        refresh();
      }
    );
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""
