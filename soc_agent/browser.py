"""Browser adapters for structured DOM-first business workflows."""

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class BrowserAdapterError(RuntimeError):
    """Raised when a browser workflow cannot collect structured data."""

    def __init__(
        self,
        message: str,
        attempts: int = 1,
        failures: Tuple[str, ...] = (),
        diagnostics_path: Optional[str] = None,
    ):
        super().__init__(message)
        self.attempts = attempts
        self.failures = failures
        self.diagnostics_path = diagnostics_path


@dataclass(frozen=True)
class ERPSelectors:
    invoice_input: str = '[data-testid="invoice-id-input"]'
    search_submit: str = '[data-testid="invoice-search-submit"]'
    record: str = '[data-testid="invoice-record"]'
    not_found: str = '[data-testid="invoice-not-found"]'
    field: str = "[data-field]"


@dataclass(frozen=True)
class ERPSearchResult:
    invoice_id: str
    base_url: str
    records: Tuple[Dict[str, Any], ...]
    screenshot_path: Optional[str] = None
    attempts: int = 1
    retry_errors: Tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.records)

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def duplicate(self) -> bool:
        return self.record_count > 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "base_url": self.base_url,
            "found": self.found,
            "record_count": self.record_count,
            "duplicate": self.duplicate,
            "records": list(self.records),
            "screenshot_path": self.screenshot_path,
            "attempts": self.attempts,
            "retry_errors": list(self.retry_errors),
        }


class MockERPAdapter:
    """Collect invoice data from structured selectors on the Mock ERP page."""

    def __init__(
        self,
        page,
        base_url: str,
        selectors: Optional[ERPSelectors] = None,
        timeout_ms: int = 10000,
        attempts: int = 1,
        retry_delay_seconds: float = 0.5,
        sleep_fn=None,
    ):
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than 0")
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        if retry_delay_seconds < 0:
            raise ValueError(
                "retry_delay_seconds must not be negative"
            )
        self.page = page
        self.base_url = base_url.rstrip("/") + "/"
        self.selectors = selectors or ERPSelectors()
        self.timeout_ms = timeout_ms
        self.attempts = attempts
        self.retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep_fn or time.sleep

    def search(
        self,
        invoice_id: str,
        screenshot_path: Optional[str] = None,
    ) -> ERPSearchResult:
        query = invoice_id.strip()
        if not query:
            raise ValueError("invoice_id must not be empty")

        retry_errors = []
        for attempt in range(1, self.attempts + 1):
            try:
                records = self._search_once(query)
            except Exception as error:
                retry_errors.append(str(error))
                if attempt < self.attempts:
                    self._sleep(self.retry_delay_seconds)
                continue

            captured_path = None
            if screenshot_path:
                path = Path(screenshot_path).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(path), full_page=True)
                captured_path = str(path)

            return ERPSearchResult(
                invoice_id=query,
                base_url=self.base_url,
                records=tuple(records),
                screenshot_path=captured_path,
                attempts=attempt,
                retry_errors=tuple(retry_errors),
            )

        diagnostics_path = self._capture_failure_diagnostics(
            query,
            retry_errors,
            screenshot_path,
        )
        raise BrowserAdapterError(
            (
                f"ERP browser search failed for {query} after "
                f"{self.attempts} attempt(s): {retry_errors[-1]}"
            ),
            attempts=self.attempts,
            failures=tuple(retry_errors),
            diagnostics_path=diagnostics_path,
        )

    def _search_once(self, query: str):
        self.page.goto(
            self.base_url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        self.page.fill(
            self.selectors.invoice_input,
            query,
            timeout=self.timeout_ms,
        )
        self.page.click(
            self.selectors.search_submit,
            timeout=self.timeout_ms,
        )
        self.page.wait_for_selector(
            (
                f"{self.selectors.record}, "
                f"{self.selectors.not_found}"
            ),
            timeout=self.timeout_ms,
        )
        return self.page.locator(
            self.selectors.record
        ).evaluate_all(
            """
            (elements, fieldSelector) => elements.map((element) => {
              const result = {};
              element.querySelectorAll(fieldSelector).forEach((field) => {
                result[field.dataset.field] = field.textContent.trim();
              });
              return result;
            })
            """,
            self.selectors.field,
        )

    def _capture_failure_diagnostics(
        self,
        query: str,
        failures: List[str],
        screenshot_path: Optional[str],
    ) -> Optional[str]:
        if not screenshot_path:
            return None
        base_path = Path(screenshot_path).expanduser().resolve()
        base_path.parent.mkdir(parents=True, exist_ok=True)
        failure_screenshot = base_path.with_name(
            f"{base_path.stem}-failure.png"
        )
        diagnostics_path = base_path.with_name(
            f"{base_path.stem}-diagnostics.txt"
        )
        try:
            self.page.screenshot(
                path=str(failure_screenshot),
                full_page=True,
            )
        except Exception:
            pass
        content = [
            f"Invoice: {query}",
            f"URL: {self.base_url}",
            f"Attempts: {self.attempts}",
            f"Failure screenshot: {failure_screenshot}",
            "",
            "Errors:",
        ]
        content.extend(
            f"[{index}] {failure}"
            for index, failure in enumerate(failures, start=1)
        )
        diagnostics_path.write_text(
            "\n".join(content) + "\n",
            encoding="utf-8",
        )
        return str(diagnostics_path)


class PlaywrightBrowserSession:
    """Manage a Chromium/Chrome Playwright session."""

    def __init__(
        self,
        executable_path: Optional[str] = None,
        headless: bool = True,
    ):
        self.executable_path = (
            executable_path or find_browser_executable()
        )
        self.headless = headless
        self._playwright = None
        self._browser = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserAdapterError(
                "Playwright is required for browser automation"
            ) from error

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                executable_path=self.executable_path,
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    def new_page(self):
        if self._browser is None:
            raise BrowserAdapterError("browser session is not started")
        return self._browser.new_page()

    def __exit__(self, exc_type, exc_value, traceback):
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


def find_browser_executable() -> str:
    configured = os.getenv("SOC_BROWSER_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured

    candidates = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate

    for command in (
        "google-chrome",
        "chromium",
        "chromium-browser",
        "msedge",
    ):
        executable = shutil.which(command)
        if executable:
            return executable
    raise BrowserAdapterError(
        "Chrome, Edge, or Chromium executable was not found"
    )
