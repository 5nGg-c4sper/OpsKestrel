"""Stateful enterprise-like Mock ERP used for browser reliability tests."""

import csv
import io
import json
import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import parse_qs, urlparse

from opskestrel.mock_erp import MockERPStore


SESSION_COOKIE = "opskestrel_erp_session"


@dataclass
class EnterpriseERPConfig:
    require_login: bool = True
    username: str = "demo"
    password: str = "demo"
    session_ttl_seconds: float = 300.0
    page_size: int = 10
    slow_invoices: Dict[str, float] = field(default_factory=dict)
    fail_once_invoices: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.username or not self.password:
            raise ValueError("Mock ERP username and password are required")
        if self.session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be greater than 0")
        if self.page_size < 1:
            raise ValueError("page_size must be at least 1")
        if any(delay < 0 for delay in self.slow_invoices.values()):
            raise ValueError("slow invoice delays must not be negative")
        if any(count < 0 for count in self.fail_once_invoices.values()):
            raise ValueError("failure counts must not be negative")

    @classmethod
    def from_file(cls, path) -> "EnterpriseERPConfig":
        source_path = Path(path).expanduser().resolve()
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("failure config must be a JSON object")
        unknown = sorted(
            set(payload)
            - {"slow_invoices", "fail_once_invoices"}
        )
        if unknown:
            raise ValueError(
                "unknown failure config fields: "
                + ", ".join(unknown)
            )
        if not isinstance(payload.get("slow_invoices", {}), dict):
            raise ValueError("slow_invoices must be an object")
        if not isinstance(payload.get("fail_once_invoices", {}), dict):
            raise ValueError("fail_once_invoices must be an object")
        return cls(
            slow_invoices={
                str(key): float(value)
                for key, value in payload.get(
                    "slow_invoices",
                    {},
                ).items()
            },
            fail_once_invoices={
                str(key): int(value)
                for key, value in payload.get(
                    "fail_once_invoices",
                    {},
                ).items()
            },
        )


class EnterpriseERPStore(MockERPStore):
    @property
    def all_records(self) -> List[Dict]:
        records = []
        for key in sorted(self.records_by_id):
            records.extend(self.records_by_id[key])
        return records

    def page(
        self,
        page: int,
        page_size: int,
    ):
        records = self.all_records
        total = len(records)
        start = (page - 1) * page_size
        return records[start:start + page_size], total


class EnterpriseERPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        store: EnterpriseERPStore,
        config: EnterpriseERPConfig,
    ):
        super().__init__(server_address, EnterpriseERPHandler)
        self.store = store
        self.config = config
        self.sessions = {}
        self.failure_counts = {
            key.casefold(): value
            for key, value in config.fail_once_invoices.items()
        }

    def create_session(self) -> str:
        token = secrets.token_urlsafe(24)
        self.sessions[token] = (
            time.monotonic() + self.config.session_ttl_seconds
        )
        return token

    def session_valid(self, token: Optional[str]) -> bool:
        if not self.config.require_login:
            return True
        if not token:
            return False
        expires_at = self.sessions.get(token)
        if expires_at is None:
            return False
        if expires_at <= time.monotonic():
            self.sessions.pop(token, None)
            return False
        self.sessions[token] = (
            time.monotonic() + self.config.session_ttl_seconds
        )
        return True

    def invalidate_session(self, token: Optional[str]) -> None:
        if token:
            self.sessions.pop(token, None)

    def maybe_fail(self, invoice_id: str) -> Optional[int]:
        key = invoice_id.casefold()
        delay = self.config.slow_invoices.get(invoice_id)
        if delay is None:
            delay = self.config.slow_invoices.get(key, 0.0)
        if delay:
            time.sleep(delay)
        remaining = self.failure_counts.get(key, 0)
        if remaining > 0:
            self.failure_counts[key] = remaining - 1
            return HTTPStatus.SERVICE_UNAVAILABLE
        return None


class EnterpriseERPHandler(BaseHTTPRequestHandler):
    server: EnterpriseERPServer

    def do_GET(self):
        parsed = urlparse(self.path)
        token = self._session_token()
        if parsed.path == "/login":
            self._send_html(_login_html())
            return
        if parsed.path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "unique_invoices": (
                        self.server.store.unique_invoice_count
                    ),
                    "require_login": self.server.config.require_login,
                    "active_sessions": len(self.server.sessions),
                }
            )
            return
        if not self.server.session_valid(token):
            if parsed.path == "/":
                self._redirect("/login")
            else:
                self._send_unauthorized()
            return
        if parsed.path == "/":
            self._send_html(_app_html())
            return
        if parsed.path == "/api/session":
            self._send_json({"authenticated": True})
            return
        if parsed.path == "/api/invoices":
            self._handle_invoices(parsed)
            return
        if parsed.path == "/api/export.csv":
            self._handle_csv_export(parsed)
            return
        self._send_json(
            {"error": "not found"},
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            self._handle_login()
            return
        if parsed.path == "/api/logout":
            token = self._session_token()
            self.server.invalidate_session(token)
            self._send_json(
                {"authenticated": False},
                headers={
                    "Set-Cookie": (
                        f"{SESSION_COOKIE}=; Path=/; Max-Age=0; "
                        "HttpOnly; SameSite=Lax"
                    )
                },
            )
            return
        self._send_json(
            {"error": "not found"},
            status=HTTPStatus.NOT_FOUND,
        )

    def _handle_login(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )
        except (ValueError, json.JSONDecodeError):
            self._send_json(
                {"error": "invalid login payload"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if (
            payload.get("username") != self.server.config.username
            or payload.get("password") != self.server.config.password
        ):
            self._send_json(
                {"error": "invalid username or password"},
                status=HTTPStatus.UNAUTHORIZED,
            )
            return
        token = self.server.create_session()
        self._send_json(
            {"authenticated": True},
            headers={
                "Set-Cookie": (
                    f"{SESSION_COOKIE}={token}; Path=/; "
                    "HttpOnly; SameSite=Lax"
                )
            },
        )

    def _handle_invoices(self, parsed):
        query = parse_qs(parsed.query)
        invoice_id = query.get("invoice_id", [""])[0].strip()
        page_number = max(1, int(query.get("page", ["1"])[0]))
        page_size = max(
            1,
            int(
                query.get(
                    "page_size",
                    [str(self.server.config.page_size)],
                )[0]
            ),
        )
        if invoice_id:
            failure = self.server.maybe_fail(invoice_id)
            if failure is not None:
                self._send_json(
                    {"error": "injected ERP failure"},
                    status=failure,
                )
                return
            records = self.server.store.search(invoice_id)
            if not records:
                self._send_json(
                    {"error": "invoice not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_json(
                {
                    "invoice_id": records[0]["invoice_id"],
                    "count": len(records),
                    "total": len(records),
                    "page": 1,
                    "page_size": len(records),
                    "records": records,
                }
            )
            return

        records, total = self.server.store.page(
            page_number,
            page_size,
        )
        self._send_json(
            {
                "count": len(records),
                "total": total,
                "page": page_number,
                "page_size": page_size,
                "records": records,
            }
        )

    def _handle_csv_export(self, parsed):
        invoice_id = parse_qs(parsed.query).get(
            "invoice_id",
            [""],
        )[0].strip()
        records = (
            self.server.store.search(invoice_id)
            if invoice_id
            else self.server.store.all_records
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "invoice_id",
                "customer_id",
                "currency",
                "amount",
                "status",
                "due_date",
            ],
        )
        writer.writeheader()
        writer.writerows(records)
        encoded = output.getvalue().encode("utf-8-sig")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="erp-invoices.csv"',
        )
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _send_unauthorized(self):
        self._send_json(
            {"error": "authentication required"},
            status=HTTPStatus.UNAUTHORIZED,
        )

    def _redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(self, content):
        self._send_bytes(
            content.encode("utf-8"),
            "text/html; charset=utf-8",
        )

    def _send_json(self, payload, status=HTTPStatus.OK, headers=None):
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
            headers=headers,
        )

    def _send_bytes(
        self,
        content,
        content_type,
        status=HTTPStatus.OK,
        headers=None,
    ):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        return


def create_enterprise_erp_server(
    data_path,
    host: str = "127.0.0.1",
    port: int = 0,
    config: Optional[EnterpriseERPConfig] = None,
) -> EnterpriseERPServer:
    store = EnterpriseERPStore.from_file(data_path)
    return EnterpriseERPServer(
        (host, port),
        store,
        config or EnterpriseERPConfig(),
    )


def _login_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpsKestrel Mock ERP Login</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #f4f6f8;
           color: #17202a; margin: 0; }
    main { max-width: 420px; margin: 100px auto; background: white;
           padding: 32px; border-radius: 14px; box-shadow: 0 12px 30px #17202a20; }
    form { display: grid; gap: 14px; }
    input, button { padding: 12px; border-radius: 8px; font-size: 16px; }
    input { border: 1px solid #c8d0d8; }
    button { border: 0; background: #1463ff; color: white; cursor: pointer; }
    #login-error { color: #c53727; min-height: 20px; }
  </style>
</head>
<body>
  <main>
    <h1>Mock ERP Login</h1>
    <form id="login-form" data-testid="login-form">
      <input id="username" data-testid="login-username"
             placeholder="Username" autocomplete="username">
      <input id="password" data-testid="login-password"
             type="password" placeholder="Password"
             autocomplete="current-password">
      <button id="login-submit" data-testid="login-submit"
              type="submit">Sign in</button>
      <div id="login-error" data-testid="login-error"></div>
    </form>
  </main>
  <script>
    document.getElementById("login-form").addEventListener(
      "submit",
      async (event) => {
        event.preventDefault();
        const response = await fetch("/api/login", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            username: document.getElementById("username").value,
            password: document.getElementById("password").value
          })
        });
        const payload = await response.json();
        if (!response.ok) {
          document.getElementById("login-error").textContent =
            payload.error || "Login failed";
          return;
        }
        window.location.href = "/";
      }
    );
  </script>
</body>
</html>
"""


def _app_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpsKestrel Mock ERP Enterprise</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #f4f6f8;
      color: #17202a; margin: 0; }}
    main {{ max-width: 980px; margin: 40px auto; padding: 0 24px; }}
    .top {{ display:flex; justify-content:space-between; align-items:center; }}
    form.search {{ display:flex; gap:10px; background:white; padding:16px;
      border-radius:12px; }}
    input {{ flex:1; padding:11px; border:1px solid #c8d0d8;
      border-radius:8px; font-size:16px; }}
    button {{ padding:10px 18px; border:0; border-radius:8px;
      background:#1463ff; color:white; cursor:pointer; }}
    #search-status {{ margin:20px 0; color:#59636e; }}
    .record {{ background:white; padding:18px; border-radius:12px;
      margin-bottom:12px; }}
    dl {{ display:grid; grid-template-columns:150px 1fr; gap:8px 18px; }}
    dt {{ color:#59636e; }} dd {{ margin:0; font-weight:600; }}
    .pager {{ display:flex; gap:10px; align-items:center; margin:16px 0; }}
  </style>
</head>
<body>
  <main>
    <div class="top">
      <h1>Mock ERP Invoice Portal</h1>
      <div>
        <button id="export-csv" data-testid="export-csv">Export CSV</button>
        <button id="logout" data-testid="logout">Sign out</button>
      </div>
    </div>
    <form class="search" id="invoice-search" data-testid="invoice-search">
      <input id="invoice-id" data-testid="invoice-id-input"
             placeholder="Invoice ID (leave blank to list)">
      <button id="search-submit" data-testid="invoice-search-submit"
              type="submit">Search</button>
    </form>
    <div class="pager">
      <button id="page-prev" data-testid="page-prev">Previous</button>
      <span id="page-status" data-testid="page-status">Page 1</span>
      <button id="page-next" data-testid="page-next">Next</button>
    </div>
    <div id="search-status" data-testid="search-status"></div>
    <section id="invoice-result" data-testid="invoice-result"></section>
  </main>
  <script>
    let currentPage = 1;
    const input = document.getElementById("invoice-id");
    const status = document.getElementById("search-status");
    const result = document.getElementById("invoice-result");
    const pageStatus = document.getElementById("page-status");

    function addField(article, name, value) {{
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = name;
      dd.dataset.field = name;
      dd.textContent = value == null ? "" : String(value);
      article.querySelector("dl").append(dt, dd);
    }}

    async function loadInvoices(page=1) {{
      currentPage = page;
      result.replaceChildren();
      status.textContent = "Loading...";
      const params = new URLSearchParams({{page: String(page)}});
      if (input.value.trim()) params.set("invoice_id", input.value.trim());
      const response = await fetch("/api/invoices?" + params.toString());
      if (response.status === 401) {{
        window.location.href = "/login";
        return;
      }}
      const payload = await response.json();
      if (!response.ok) {{
        status.textContent = payload.error || "Invoice not found.";
        if (response.status >= 500) {{
          const failure = document.createElement("div");
          failure.id = "erp-error";
          failure.dataset.testid = "erp-error";
          failure.textContent = payload.error || "ERP server error";
          result.append(failure);
          return;
        }}
        const missing = document.createElement("div");
        missing.id = "invoice-not-found";
        missing.dataset.testid = "invoice-not-found";
        missing.textContent = "No matching ERP invoice.";
        result.append(missing);
        return;
      }}
      status.textContent = payload.count + " record(s), " +
        payload.total + " total";
      pageStatus.textContent = "Page " + payload.page;
      payload.records.forEach((record, index) => {{
        const article = document.createElement("article");
        article.className = "record";
        article.dataset.record = String(index);
        article.dataset.testid = "invoice-record";
        const heading = document.createElement("h2");
        heading.textContent = record.invoice_id;
        const list = document.createElement("dl");
        article.append(heading, list);
        ["invoice_id", "customer_id", "currency", "amount",
         "status", "due_date"].forEach((name) => {{
          addField(article, name, record[name]);
        }});
        result.append(article);
      }});
    }}

    document.getElementById("invoice-search").addEventListener(
      "submit", (event) => {{
        event.preventDefault();
        loadInvoices(1);
      }}
    );
    document.getElementById("page-prev").addEventListener(
      "click", () => loadInvoices(Math.max(1, currentPage - 1))
    );
    document.getElementById("page-next").addEventListener(
      "click", () => loadInvoices(currentPage + 1)
    );
    document.getElementById("logout").addEventListener(
      "click", async () => {{
        await fetch("/api/logout", {{method: "POST"}});
        window.location.href = "/login";
      }}
    );
    document.getElementById("export-csv").addEventListener(
      "click", () => {{
        const params = new URLSearchParams();
        if (input.value.trim()) params.set("invoice_id", input.value.trim());
        window.location.href = "/api/export.csv?" + params.toString();
      }}
    );
    loadInvoices(1);
  </script>
</body>
</html>
"""
