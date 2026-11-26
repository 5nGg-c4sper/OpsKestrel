"""Local read/write operations console for SOC Agent."""

import json
import subprocess
import sys
import threading
import time
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
    ):
        self.project_root = Path(project_root).expanduser().resolve()
        self.reports_dir = Path(reports_dir).expanduser().resolve()
        self.queue_db = str(queue_db)
        self.command_factory = command_factory or self._default_command
        self._process = None
        self._log_file = None
        self._output_dir = None
        self._started_at = None
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
        }

    def start_invoice_demo(self):
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return {"started": False, "error": "demo already running"}
            if self._log_file is not None:
                self._log_file.close()
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            output_dir = self.reports_dir / f"console-demo-{timestamp}"
            output_dir.mkdir(parents=True, exist_ok=True)
            command = self.command_factory(output_dir)
            log_path = output_dir / "demo.log"
            log_file = log_path.open("w", encoding="utf-8")
            self._process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._log_file = log_file
            self._output_dir = output_dir
            self._started_at = time.time()
            return {
                "started": True,
                "output_dir": str(output_dir),
            }

    def demo_status(self):
        if self._process is None:
            return {"state": "idle"}
        return {
            "state": (
                "running"
                if self._process.poll() is None
                else "finished"
            ),
            "exit_code": self._process.poll(),
            "started_at": self._started_at,
            "output_dir": (
                str(self._output_dir) if self._output_dir else None
            ),
        }

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
):
    state = ConsoleState(
        project_root,
        reports_dir,
        queue_db,
        command_factory=command_factory,
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
    button { border:0; border-radius:8px; padding:10px 16px;
      background:#1463ff; color:white; cursor:pointer; }
    section { background:white; border-radius:12px; padding:18px;
      margin:18px 0; box-shadow:0 8px 24px #17202a12; }
    table { width:100%; border-collapse:collapse; }
    th,td { text-align:left; padding:10px; border-bottom:1px solid #e2e7ec; }
    .muted { color:#65717c; } a { color:#1463ff; }
    .status-passed { color:#16834b; font-weight:600; }
    .status-failed { color:#c53727; font-weight:600; }
  </style>
</head>
<body>
  <main>
    <div class="bar">
      <h1>SOC Agent Console</h1>
      <button id="run-demo">运行发票对账 Demo</button>
    </div>
    <div id="demo-status" class="muted">Demo idle</div>
    <section>
      <h2>在线 Worker</h2>
      <div id="workers" class="muted">Loading...</div>
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
    async function refresh() {
      const response = await fetch("/api/overview");
      const payload = await response.json();
      document.getElementById("workers").textContent =
        payload.workers.length + " worker(s) online";
      const rows = payload.reports.map((report) => {
        const duration = report.duration_seconds == null ? "-" :
          Number(report.duration_seconds).toFixed(2) + "s";
        return `<tr><td>${report.name}</td><td>${report.type}</td>
          <td class="status-${report.status}">${report.status}</td>
          <td>${duration}</td><td><a href="${report.url}">打开</a></td></tr>`;
      });
      document.getElementById("reports").innerHTML = rows.join("");
      document.getElementById("demo-status").textContent =
        "Demo " + payload.demo.state +
        (payload.demo.exit_code == null ? "" :
          " (exit " + payload.demo.exit_code + ")");
    }
    document.getElementById("run-demo").addEventListener(
      "click", async () => {
        const response = await fetch("/api/demo/run", {method:"POST"});
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
