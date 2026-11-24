"""Build and persist task suite execution reports."""

import json
import re
from pathlib import Path

from soc_agent.suite import SuiteResult


class SuiteReportWriter:
    """Write suite results as JSON files."""

    def __init__(self, output_dir="reports"):
        self.output_dir = Path(output_dir)

    def write(self, result: SuiteResult) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        safe_suite_name = self._safe_suite_name(result.suite_name)
        filename = (
            f"{result.finished_at.strftime('%Y%m%d-%H%M%S')}-"
            f"{safe_suite_name}.json"
        )
        path = self._unique_path(self.output_dir / filename)

        result.report_path = str(path)
        payload = {
            "suite_name": result.suite_name,
            "status": "passed" if result.successful else "failed",
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "duration_seconds": result.duration_seconds,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "timed_out": result.timed_out,
            "cancelled": result.cancelled,
            "stopped_early": result.stopped_early,
            "results": [
                task.model_dump(mode="json")
                for task in result.results
            ],
            "report_path": result.report_path,
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)

        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(content + "\n", encoding="utf-8")
        temp_path.replace(path)

        return path

    @staticmethod
    def _safe_suite_name(suite_name: str) -> str:
        safe_name = re.sub(
            r"[^\w.-]+",
            "-",
            suite_name,
            flags=re.UNICODE,
        )
        safe_name = safe_name.strip("._-")
        return safe_name or "suite"

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path

        index = 1
        while True:
            candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
            if not candidate.exists():
                return candidate
            index += 1
