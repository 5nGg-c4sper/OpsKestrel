"""Build and persist workflow execution reports."""

import json
import re
from pathlib import Path

from soc_agent.task_models import WorkflowResult


class WorkflowReportWriter:
    """Write workflow results as JSON files."""

    def __init__(self, output_dir="reports"):
        self.output_dir = Path(output_dir)

    def write(self, result: WorkflowResult) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        safe_workflow_name = self._safe_workflow_name(
            result.workflow_name
        )
        filename = (
            f"{result.finished_at.strftime('%Y%m%d-%H%M%S')}-"
            f"{safe_workflow_name}.json"
        )
        path = self._unique_path(self.output_dir / filename)

        result.report_path = str(path)
        payload = result.model_dump(mode="json")
        content = json.dumps(payload, ensure_ascii=False, indent=2)

        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(content + "\n", encoding="utf-8")
        temp_path.replace(path)

        return path

    @staticmethod
    def _safe_workflow_name(workflow_name: str) -> str:
        safe_name = re.sub(
            r"[^\w.-]+",
            "-",
            workflow_name,
            flags=re.UNICODE,
        )
        safe_name = safe_name.strip("._-")
        return safe_name or "workflow"

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
