"""Build and persist task execution reports."""

import json
import re
import shutil
from pathlib import Path

from soc_agent.task_models import TaskResult


class ReportWriter:
    """Write task results as JSON files."""

    def __init__(self, output_dir="reports"):
        self.output_dir = Path(output_dir)

    def write(self, result: TaskResult) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = result.finished_at or result.started_at
        safe_task_name = self._safe_task_name(result.task_name)
        filename = (
            f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{safe_task_name}.json"
        )
        path = self._unique_path(self.output_dir / filename)

        result.report_path = str(path)
        self._copy_screenshots(result, path)
        payload = result.model_dump(mode="json")
        content = json.dumps(payload, ensure_ascii=False, indent=2)

        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(content + "\n", encoding="utf-8")
        temp_path.replace(path)

        return path

    def _copy_screenshots(self, result: TaskResult, report_path: Path) -> None:
        artifact_dir = self.output_dir / "artifacts" / report_path.stem

        for step in result.steps:
            if not step.screenshot:
                continue

            source = Path(step.screenshot)
            if not source.is_file():
                continue

            artifact_dir.mkdir(parents=True, exist_ok=True)
            suffix = source.suffix or ".png"
            target = artifact_dir / f"step-{step.index:03d}{suffix}"
            shutil.copy2(source, target)
            step.screenshot = str(target.relative_to(self.output_dir))

    @staticmethod
    def _safe_task_name(task_name: str) -> str:
        safe_name = re.sub(r"[^\w.-]+", "-", task_name, flags=re.UNICODE)
        safe_name = safe_name.strip("._-")
        return safe_name or "task"

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
