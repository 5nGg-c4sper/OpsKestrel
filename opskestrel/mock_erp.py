"""Local ERP web fixture used by browser automation scenarios."""

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Union
from urllib.parse import parse_qs, urlparse


class MockERPDataError(ValueError):
    """Raised when the ERP fixture cannot be loaded."""


class MockERPStore:
    def __init__(self, records: List[Dict]):
        self.records_by_id = {}
        for record in records:
            invoice_id = str(record.get("invoice_id", "")).strip()
            if not invoice_id:
                raise MockERPDataError(
                    "ERP fixture record is missing invoice_id"
                )
            self.records_by_id.setdefault(
                invoice_id.casefold(),
                [],
            ).append(dict(record))

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "MockERPStore":
        source_path = Path(path).expanduser().resolve()
        try:
            payload = json.loads(
                source_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise MockERPDataError(
                f"failed to load ERP fixture {source_path}: {error}"
            ) from error
        if isinstance(payload, dict):
            payload = payload.get("invoices")
        if not isinstance(payload, list):
            raise MockERPDataError(
                "ERP fixture must be a list or contain an invoices list"
            )
        return cls(payload)

    def search(self, invoice_id: str) -> List[Dict]:
        return list(
            self.records_by_id.get(invoice_id.strip().casefold(), [])
        )

    @property
    def unique_invoice_count(self) -> int:
        return len(self.records_by_id)


class MockERPHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        store: MockERPStore,
    ):
        super().__init__(server_address, MockERPRequestHandler)
        self.store = store


class MockERPRequestHandler(BaseHTTPRequestHandler):
    server: MockERPHTTPServer

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(_mock_erp_html())
            return
        if parsed.path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "unique_invoices": (
                        self.server.store.unique_invoice_count
                    ),
                }
            )
            return
        if parsed.path == "/api/invoices":
            invoice_id = parse_qs(parsed.query).get(
                "invoice_id",
                [""],
            )[0]
            if not invoice_id.strip():
                self._send_json(
                    {"error": "invoice_id is required"},
                    status=HTTPStatus.BAD_REQUEST,
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
                    "records": records,
                }
            )
            return
        self._send_json(
            {"error": "not found"},
            status=HTTPStatus.NOT_FOUND,
        )

    def log_message(self, format, *args):
        return

    def _send_html(self, content: str):
        encoded = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def create_mock_erp_server(
    data_path: Union[str, Path],
    host: str = "127.0.0.1",
    port: int = 0,
) -> MockERPHTTPServer:
    store = MockERPStore.from_file(data_path)
    return MockERPHTTPServer((host, port), store)


def _mock_erp_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpsKestrel Mock ERP</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
           margin: 0; background: #f4f6f8; color: #17202a; }
    main { max-width: 860px; margin: 48px auto; padding: 0 24px; }
    h1 { margin-bottom: 8px; }
    .subtitle { color: #59636e; margin-bottom: 28px; }
    form { display: flex; gap: 10px; background: white; padding: 18px;
           border-radius: 12px; box-shadow: 0 8px 24px #17202a14; }
    input { flex: 1; padding: 11px 12px; border: 1px solid #c8d0d8;
            border-radius: 8px; font-size: 16px; }
    button { padding: 11px 20px; border: 0; border-radius: 8px;
             background: #1463ff; color: white; font-size: 16px;
             cursor: pointer; }
    #search-status { margin: 24px 0 12px; color: #59636e; }
    .record { background: white; padding: 20px; border-radius: 12px;
              margin-bottom: 14px; box-shadow: 0 8px 24px #17202a14; }
    .record h2 { margin-top: 0; }
    dl { display: grid; grid-template-columns: 150px 1fr;
         gap: 10px 18px; margin: 0; }
    dt { color: #59636e; }
    dd { margin: 0; font-weight: 600; }
    .missing { background: #fff1f0; border: 1px solid #ffccc7;
               padding: 16px; border-radius: 10px; }
  </style>
</head>
<body>
  <main>
    <h1>Mock ERP Invoice Portal</h1>
    <p class="subtitle">Search an invoice to inspect ERP billing data.</p>
    <form id="invoice-search" data-testid="invoice-search">
      <label for="invoice-id" hidden>Invoice ID</label>
      <input id="invoice-id" data-testid="invoice-id-input"
             name="invoice_id" placeholder="INV-1001" autocomplete="off">
      <button id="search-submit" data-testid="invoice-search-submit"
              type="submit">Search</button>
    </form>
    <div id="search-status" data-testid="search-status">
      Enter an invoice ID.
    </div>
    <section id="invoice-result" data-testid="invoice-result"></section>
  </main>
  <script>
    const form = document.getElementById("invoice-search");
    const input = document.getElementById("invoice-id");
    const status = document.getElementById("search-status");
    const result = document.getElementById("invoice-result");

    function addField(recordElement, name, value) {
      const term = document.createElement("dt");
      term.textContent = name;
      const description = document.createElement("dd");
      description.dataset.field = name;
      description.textContent = value == null ? "" : String(value);
      recordElement.querySelector("dl").append(term, description);
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const invoiceId = input.value.trim();
      result.replaceChildren();
      if (!invoiceId) {
        status.textContent = "Invoice ID is required.";
        return;
      }
      status.textContent = "Searching...";
      try {
        const response = await fetch(
          "/api/invoices?invoice_id=" + encodeURIComponent(invoiceId)
        );
        const payload = await response.json();
        if (!response.ok) {
          status.textContent = payload.error || "Invoice not found.";
          const missing = document.createElement("div");
          missing.className = "missing";
          missing.id = "invoice-not-found";
          missing.dataset.testid = "invoice-not-found";
          missing.textContent = "No matching ERP invoice.";
          result.append(missing);
          return;
        }
        status.textContent =
          payload.count + " ERP record(s) found for " + payload.invoice_id;
        payload.records.forEach((record, index) => {
          const article = document.createElement("article");
          article.className = "record";
          article.dataset.record = String(index);
          article.dataset.testid = "invoice-record";
          const heading = document.createElement("h2");
          heading.textContent = record.invoice_id;
          const list = document.createElement("dl");
          article.append(heading, list);
          ["invoice_id", "customer_id", "currency", "amount",
           "status", "due_date"].forEach((name) => {
            addField(article, name, record[name]);
          });
          result.append(article);
        });
      } catch (error) {
        status.textContent = "ERP request failed: " + error;
      }
    });
  </script>
</body>
</html>
"""
