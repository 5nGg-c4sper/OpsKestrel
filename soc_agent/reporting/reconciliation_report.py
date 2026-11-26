"""Render business-friendly HTML reconciliation reports."""

import html
import os
from pathlib import Path

from soc_agent.erp_reconciliation import BrowserReconciliationReport
from soc_agent.reconciliation import ReconciliationStatus


class ReconciliationHTMLReportWriter:
    """Write a self-contained filterable reconciliation report."""

    def write(
        self,
        report: BrowserReconciliationReport,
        output_path,
    ) -> Path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.render(report, path.parent)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
        return path

    def render(
        self,
        report: BrowserReconciliationReport,
        output_dir,
    ) -> str:
        summary = report.reconciliation.summary
        lookup_by_id = {
            lookup.invoice_id.casefold(): lookup
            for lookup in report.lookups
        }
        cards = self._render_cards(
            summary,
            len(report.collection_errors),
        )
        filters = self._render_filters(summary)
        rows = "\n".join(
            self._render_result_row(
                result,
                lookup_by_id,
                Path(output_dir),
            )
            for result in report.reconciliation.results
        )
        errors = self._render_collection_errors(report)

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ERP Invoice Reconciliation</title>
  <style>
    :root {{
      --bg: #f4f6f8; --card: #fff; --text: #17202a;
      --muted: #65717c; --line: #d9e0e6; --blue: #1463ff;
      --green: #16834b; --red: #c53727; --amber: #ad6800;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ max-width: 1320px; margin: 36px auto; padding: 0 24px; }}
    h1 {{ margin: 0 0 8px; }}
    .muted {{ color: var(--muted); }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr);
      gap: 12px; margin: 26px 0; }}
    .card {{ background: var(--card); border: 1px solid var(--line);
      border-radius: 12px; padding: 16px; }}
    .card strong {{ display: block; font-size: 28px; margin-top: 6px; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0; }}
    .filter {{ border: 1px solid var(--line); background: white;
      border-radius: 999px; padding: 8px 13px; cursor: pointer; }}
    .filter.active {{ border-color: var(--blue); color: var(--blue); }}
    input {{ min-width: 300px; padding: 10px 12px; border: 1px solid var(--line);
      border-radius: 9px; font-size: 15px; }}
    .table-wrap {{ overflow: auto; background: white; border-radius: 12px;
      border: 1px solid var(--line); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1000px; }}
    th, td {{ text-align: left; padding: 13px 14px; border-bottom: 1px solid var(--line);
      vertical-align: top; }}
    th {{ background: #eef2f6; }}
    .status {{ font-weight: 650; white-space: nowrap; }}
    .status-matched {{ color: var(--green); }}
    .status-amount_mismatch, .status-currency_mismatch,
    .status-status_mismatch {{ color: var(--red); }}
    .status-missing_in_erp, .status-duplicate_in_erp,
    .status-invalid_input {{ color: var(--amber); }}
    .evidence a {{ color: var(--blue); }}
    .errors {{ margin-top: 24px; padding: 18px; border-radius: 12px;
      background: #fff1f0; border: 1px solid #ffccc7; }}
    .empty {{ padding: 30px; text-align: center; color: var(--muted); }}
    @media (max-width: 800px) {{
      .cards {{ grid-template-columns: repeat(2, 1fr); }}
      input {{ min-width: 100%; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>ERP 发票对账报告</h1>
    <div class="muted">Expected CSV: {html.escape(report.expected_csv)}</div>
    {cards}
    {filters}
    <div class="toolbar">
      <input id="invoice-filter" placeholder="搜索发票号或差异内容">
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>发票号</th><th>结果</th><th>预期金额</th>
            <th>ERP 金额</th><th>说明</th><th>证据</th>
          </tr>
        </thead>
        <tbody id="result-body">
          {rows or '<tr><td colspan="6" class="empty">没有记录</td></tr>'}
        </tbody>
      </table>
    </div>
    {errors}
  </main>
  <script>
    let activeFilter = "all";
    const search = document.getElementById("invoice-filter");
    const rows = Array.from(document.querySelectorAll("tr[data-status]"));
    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      rows.forEach((row) => {{
        const statusMatches =
          activeFilter === "all" || row.dataset.status === activeFilter;
        const queryMatches =
          !query || row.dataset.search.includes(query);
        row.hidden = !(statusMatches && queryMatches);
      }});
    }}
    document.querySelectorAll("[data-filter]").forEach((button) => {{
      button.addEventListener("click", () => {{
        activeFilter = button.dataset.filter;
        document.querySelectorAll("[data-filter]").forEach((item) => {{
          item.classList.toggle("active", item === button);
        }});
        applyFilters();
      }});
    }});
    search.addEventListener("input", applyFilters);
  </script>
</body>
</html>
"""

    def _render_cards(self, summary, collection_error_count: int) -> str:
        business_differences = summary["total"] - summary["by_status"][
            ReconciliationStatus.MATCHED.value
        ]
        cards = (
            ("总发票", summary["total"]),
            ("完全匹配", summary["by_status"]["matched"]),
            ("存在差异", business_differences),
            ("采集错误", collection_error_count),
        )
        return (
            '<section class="cards">'
            + "".join(
                (
                    f'<div class="card"><span class="muted">{html.escape(str(label))}'
                    f"</span><strong>{value}</strong></div>"
                )
                for label, value in cards
            )
            + "</section>"
        )

    def _render_filters(self, summary) -> str:
        buttons = ['<button class="filter active" data-filter="all">全部</button>']
        for status in ReconciliationStatus:
            buttons.append(
                (
                    f'<button class="filter" data-filter="{status.value}">'
                    f"{status.value} ({summary['by_status'][status.value]})"
                    "</button>"
                )
            )
        return '<div class="toolbar">' + "".join(buttons) + "</div>"

    def _render_result_row(
        self,
        result,
        lookup_by_id,
        output_dir: Path,
    ) -> str:
        expected_amount = _amount(result.expected)
        actual_amount = _amount(result.actual)
        detail = result.error or "; ".join(result.differences) or "-"
        lookup = lookup_by_id.get(result.invoice_id.casefold())
        evidence = "-"
        if lookup and lookup.screenshot_path:
            screenshot_path = Path(lookup.screenshot_path).resolve()
            relative = os.path.relpath(screenshot_path, output_dir)
            evidence = (
                f'<a href="{html.escape(relative)}" target="_blank">'
                "查看截图</a>"
            )
        searchable = " ".join(
            (
                result.invoice_id,
                result.status.value,
                detail,
                expected_amount,
                actual_amount,
            )
        ).casefold()
        return f"""
          <tr data-status="{result.status.value}"
              data-search="{html.escape(searchable)}">
            <td>{html.escape(result.invoice_id)}</td>
            <td class="status status-{result.status.value}">
              {result.status.value}
            </td>
            <td>{html.escape(expected_amount)}</td>
            <td>{html.escape(actual_amount)}</td>
            <td>{html.escape(detail)}</td>
            <td class="evidence">{evidence}</td>
          </tr>
        """

    def _render_collection_errors(self, report) -> str:
        if not report.collection_errors:
            return ""
        items = "".join(
            (
                f"<li>{html.escape(error.invoice_id)}: "
                f"{html.escape(error.error or '')}</li>"
            )
            for error in report.collection_errors
        )
        return (
            '<section class="errors"><strong>浏览器采集错误</strong>'
            f"<ul>{items}</ul></section>"
        )


def _amount(record) -> str:
    if isinstance(record, list):
        return f"{len(record)} records"
    if not isinstance(record, dict):
        return "-"
    value = record.get("amount")
    return str(value) if value is not None else "-"
