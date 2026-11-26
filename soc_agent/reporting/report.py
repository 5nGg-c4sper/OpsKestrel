"""Build and persist task execution reports."""

import json
import re
import shutil
from pathlib import Path

from soc_agent.task_models import TaskResult, TaskStatus


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
        self._write_failure_log(result, path)
        payload = result.model_dump(mode="json")
        content = json.dumps(payload, ensure_ascii=False, indent=2)

        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(content + "\n", encoding="utf-8")
        temp_path.replace(path)

        return path

    def _copy_screenshots(self, result: TaskResult, report_path: Path) -> None:
        artifact_dir = self.output_dir / "artifacts" / report_path.stem

        for step in result.steps:
            screenshot_fields = (
                ("screenshot", "step"),
                ("condition_screenshot", "condition-step"),
            )
            for field_name, prefix in screenshot_fields:
                source_value = getattr(step, field_name)
                if not source_value:
                    continue

                source = Path(source_value)
                if not source.is_file():
                    continue

                artifact_dir.mkdir(parents=True, exist_ok=True)
                suffix = source.suffix or ".png"
                target = (
                    artifact_dir
                    / f"{prefix}-{step.index:03d}{suffix}"
                )
                shutil.copy2(source, target)
                setattr(
                    step,
                    field_name,
                    str(target.relative_to(self.output_dir)),
                )

    def _write_failure_log(
        self,
        result: TaskResult,
        report_path: Path,
    ) -> None:
        if result.status == TaskStatus.PASSED:
            result.failure_log = None
            return

        artifact_dir = self.output_dir / "artifacts" / report_path.stem
        artifact_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"Task: {result.task_name}",
            f"Status: {result.status.value}",
            f"Duration: {result.duration_seconds:.2f} seconds",
            f"Error: {result.error or '(none)'}",
            "",
            "Steps:",
        ]

        for step in result.steps:
            lines.append(
                f"[{step.index}] {step.type.value} {step.status.value} "
                f"duration={step.duration_seconds:.2f}s"
            )
            if step.error:
                lines.append(f"  error: {step.error}")
            if step.condition_prompt is not None:
                lines.append(
                    "  condition: "
                    f"prompt={step.condition_prompt!r}, "
                    f"expected={step.condition_expected}, "
                    f"actual={step.condition_actual}, "
                    "duration="
                    f"{step.condition_duration_seconds or 0.0:.2f}s"
                )
            if step.condition_variable is not None:
                lines.append(
                    "  value condition: "
                    f"variable={step.condition_variable}, "
                    "operator="
                    f"{step.condition_operator.value if step.condition_operator else None}, "
                    f"expected_value={step.condition_expected_value!r}, "
                    f"actual_value={step.condition_actual_value!r}"
                )
            if step.condition_screenshot:
                lines.append(
                    f"  condition screenshot: "
                    f"{step.condition_screenshot}"
                )
            if step.screenshot:
                lines.append(f"  screenshot: {step.screenshot}")

        content = "\n".join(lines) + "\n"
        log_path = artifact_dir / "failure.log"
        temp_path = log_path.with_suffix(".log.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(log_path)
        result.failure_log = str(log_path.relative_to(self.output_dir))

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
