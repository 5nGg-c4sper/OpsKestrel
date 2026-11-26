"""Load workflow definitions and resolve their task files."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Union

from pydantic import ValidationError

from opskestrel.task_models import WorkflowDefinition


class WorkflowLoadError(ValueError):
    """Raised when a workflow cannot be loaded or resolved."""


@dataclass(frozen=True)
class LoadedWorkflow:
    definition: WorkflowDefinition
    workflow_path: Path
    task_paths: List[Path]
    cleanup_task_path: Optional[Path]
    parameters: Dict[str, str]


def load_workflow(
    workflow_path: Union[str, Path],
    parameter_overrides: Optional[Mapping[str, str]] = None,
) -> LoadedWorkflow:
    """Load a workflow and resolve all referenced task files."""
    source_path = Path(workflow_path).expanduser().resolve()

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise WorkflowLoadError(
            f"failed to read workflow {source_path}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise WorkflowLoadError(
            f"invalid JSON in workflow {source_path}: {error}"
        ) from error

    try:
        definition = WorkflowDefinition.model_validate(payload)
    except ValidationError as error:
        raise WorkflowLoadError(
            f"invalid workflow {source_path}: {error}"
        ) from error

    try:
        parameters = definition.resolve_parameters(
            dict(parameter_overrides or {})
        )
    except ValueError as error:
        raise WorkflowLoadError(
            f"invalid workflow parameters in {source_path}: {error}"
        ) from error

    task_paths = [
        _resolve_task_path(
            source_path.parent,
            task_file,
            source_path,
        )
        for task_file in definition.task_files
    ]
    _reject_duplicate_resolved_tasks(task_paths, source_path)

    cleanup_task_path = None
    if definition.cleanup_task is not None:
        cleanup_task_path = _resolve_task_path(
            source_path.parent,
            definition.cleanup_task,
            source_path,
        )

    return LoadedWorkflow(
        definition=definition,
        workflow_path=source_path,
        task_paths=task_paths,
        cleanup_task_path=cleanup_task_path,
        parameters=parameters,
    )


def _resolve_task_path(
    base_dir: Path,
    task_file: str,
    workflow_path: Path,
) -> Path:
    task_path = (base_dir / task_file.strip()).expanduser().resolve()
    if not task_path.is_file():
        raise WorkflowLoadError(
            "workflow task file is missing or not a file: "
            f"{task_path} (from {workflow_path})"
        )
    return task_path


def _reject_duplicate_resolved_tasks(
    task_paths,
    workflow_path: Path,
) -> None:
    seen_paths = set()
    for task_path in task_paths:
        if task_path in seen_paths:
            raise WorkflowLoadError(
                "workflow resolves duplicate task file: "
                f"{task_path} (from {workflow_path})"
            )
        seen_paths.add(task_path)
