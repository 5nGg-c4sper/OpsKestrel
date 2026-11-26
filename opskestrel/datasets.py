"""Load task datasets and resolve their task-file paths."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from pydantic import ValidationError

from opskestrel.data_sources import DataSourceLoadError, load_csv_cases
from opskestrel.task_models import (
    DatasetTargetType,
    TaskDatasetDefinition,
)


class DatasetLoadError(ValueError):
    """Raised when a task dataset cannot be loaded."""


@dataclass(frozen=True)
class LoadedDataset:
    definition: TaskDatasetDefinition
    dataset_path: Path
    target_type: DatasetTargetType
    target_path: Path

    @property
    def task_path(self) -> Optional[Path]:
        if self.target_type == DatasetTargetType.TASK:
            return self.target_path
        return None

    @property
    def workflow_path(self) -> Optional[Path]:
        if self.target_type == DatasetTargetType.WORKFLOW:
            return self.target_path
        return None


LoadedTaskDataset = LoadedDataset


def load_dataset(
    dataset_path: Union[str, Path],
) -> LoadedDataset:
    """Load a dataset and resolve its task file relative to the dataset."""
    source_path = Path(dataset_path).expanduser().resolve()

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise DatasetLoadError(
            f"failed to read dataset {source_path}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise DatasetLoadError(
            f"invalid JSON in dataset {source_path}: {error}"
        ) from error

    try:
        definition = TaskDatasetDefinition.model_validate(payload)
    except ValidationError as error:
        raise DatasetLoadError(
            f"invalid dataset {source_path}: {error}"
        ) from error

    target_type = (
        DatasetTargetType.TASK
        if definition.task is not None
        else DatasetTargetType.WORKFLOW
    )
    target_file = (
        definition.task
        if definition.task is not None
        else definition.workflow
    )
    target_path = (source_path.parent / target_file).resolve()
    if not target_path.is_file():
        if target_type == DatasetTargetType.TASK:
            message = "task file is missing or not a file"
        else:
            message = "workflow file is missing or not a file"
        raise DatasetLoadError(
            f"{message}: {target_path}"
        )

    if definition.data_source is not None:
        try:
            cases = load_csv_cases(
                definition.data_source,
                source_path.parent,
            )
        except DataSourceLoadError as error:
            raise DatasetLoadError(str(error)) from error
        definition = definition.model_copy(update={"cases": cases})

    return LoadedDataset(
        definition=definition,
        dataset_path=source_path,
        target_type=target_type,
        target_path=target_path,
    )
