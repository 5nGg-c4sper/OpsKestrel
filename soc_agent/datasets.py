"""Load task datasets and resolve their task-file paths."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from pydantic import ValidationError

from soc_agent.data_sources import DataSourceLoadError, load_csv_cases
from soc_agent.task_models import TaskDatasetDefinition


class DatasetLoadError(ValueError):
    """Raised when a task dataset cannot be loaded."""


@dataclass(frozen=True)
class LoadedTaskDataset:
    definition: TaskDatasetDefinition
    dataset_path: Path
    task_path: Path


def load_dataset(
    dataset_path: Union[str, Path],
) -> LoadedTaskDataset:
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

    task_path = (source_path.parent / definition.task).resolve()
    if not task_path.is_file():
        raise DatasetLoadError(
            f"task file is missing or not a file: {task_path}"
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

    return LoadedTaskDataset(
        definition=definition,
        dataset_path=source_path,
        task_path=task_path,
    )
