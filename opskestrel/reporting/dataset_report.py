"""Build and persist task dataset execution reports."""

import json
import re
from pathlib import Path

from opskestrel.task_models import TaskDatasetResult


class DatasetReportWriter:
    """Write dataset results as JSON files."""

    def __init__(self, output_dir="reports"):
        self.output_dir = Path(output_dir)

    def write(self, result: TaskDatasetResult) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = result.finished_at or result.started_at
        safe_dataset_name = self._safe_dataset_name(result.dataset_name)
        filename = (
            f"{timestamp.strftime('%Y%m%d-%H%M%S')}-"
            f"{safe_dataset_name}.json"
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
    def _safe_dataset_name(dataset_name: str) -> str:
        safe_name = re.sub(
            r"[^\w.-]+",
            "-",
            dataset_name,
            flags=re.UNICODE,
        )
        safe_name = safe_name.strip("._-")
        return safe_name or "dataset"

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
