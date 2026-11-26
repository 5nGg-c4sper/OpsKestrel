"""Load packaged business scenarios backed by datasets and workflows."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

from pydantic import Field, ValidationError, field_validator

from soc_agent.datasets import LoadedDataset, load_dataset
from soc_agent.task_models import DatasetTargetType, StrictModel


class ScenarioLoadError(ValueError):
    """Raised when a business scenario package is invalid."""


class ScenarioDefinition(StrictModel):
    name: str
    description: str = ""
    dataset: str
    required_apps: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)

    @field_validator("name", "dataset")
    @classmethod
    def validate_non_empty_text(cls, value):
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("required_apps", "safety_notes")
    @classmethod
    def validate_text_lists(cls, values):
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("entries must not be empty")
        return normalized


@dataclass(frozen=True)
class LoadedScenario:
    definition: ScenarioDefinition
    scenario_path: Path
    dataset: LoadedDataset


def load_scenario(scenario_path: Union[str, Path]) -> LoadedScenario:
    source_path = Path(scenario_path).expanduser().resolve()
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ScenarioLoadError(
            f"failed to read scenario {source_path}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise ScenarioLoadError(
            f"invalid JSON in scenario {source_path}: {error}"
        ) from error

    try:
        definition = ScenarioDefinition.model_validate(payload)
    except ValidationError as error:
        raise ScenarioLoadError(
            f"invalid scenario {source_path}: {error}"
        ) from error

    dataset_path = (source_path.parent / definition.dataset).resolve()
    try:
        dataset = load_dataset(dataset_path)
    except Exception as error:
        raise ScenarioLoadError(str(error)) from error

    if dataset.target_type != DatasetTargetType.WORKFLOW:
        raise ScenarioLoadError(
            "business scenarios must target a workflow dataset"
        )

    return LoadedScenario(
        definition=definition,
        scenario_path=source_path,
        dataset=dataset,
    )
