"""Load packaged business scenarios backed by datasets and workflows."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from pydantic import Field, ValidationError, field_validator

from soc_agent.browser import ERPSelectors
from soc_agent.datasets import LoadedDataset, load_dataset
from soc_agent.reconciliation_config import ReconciliationConfig
from soc_agent.task_models import DatasetTargetType, StrictModel


class ScenarioLoadError(ValueError):
    """Raised when a business scenario package is invalid."""


class ScenarioDefinition(StrictModel):
    name: str
    description: str = ""
    kind: str = "workflow_dataset"
    dataset: Optional[str] = None
    expected_input: Optional[str] = None
    erp_fixture: Optional[str] = None
    selector_profile: Optional[str] = None
    reconciliation_config: Optional[str] = None
    mock_enterprise: bool = False
    required_apps: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)

    @field_validator(
        "name",
        "dataset",
        "expected_input",
        "erp_fixture",
        "selector_profile",
        "reconciliation_config",
    )
    @classmethod
    def validate_non_empty_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value):
        if value not in {
            "workflow_dataset",
            "browser_reconciliation",
        }:
            raise ValueError("unsupported scenario kind")
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
    dataset: Optional[LoadedDataset] = None
    expected_input: Optional[Path] = None
    erp_fixture: Optional[Path] = None
    selector_profile: Optional[Path] = None
    reconciliation_config: Optional[Path] = None


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

    if definition.kind == "workflow_dataset":
        if definition.dataset is None:
            raise ScenarioLoadError(
                "workflow scenario requires dataset"
            )
        dataset_path = (
            source_path.parent / definition.dataset
        ).resolve()
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

    if not definition.expected_input or not definition.erp_fixture:
        raise ScenarioLoadError(
            "browser scenario requires expected_input and erp_fixture"
        )
    expected_input = (
        source_path.parent / definition.expected_input
    ).resolve()
    erp_fixture = (
        source_path.parent / definition.erp_fixture
    ).resolve()
    if not expected_input.is_file():
        raise ScenarioLoadError(
            f"expected input is missing: {expected_input}"
        )
    if expected_input.suffix.casefold() not in {
        ".csv",
        ".xlsx",
        ".xlsm",
        ".pdf",
    }:
        raise ScenarioLoadError(
            "expected input must be CSV or XLSX"
        )
    if not erp_fixture.is_file():
        raise ScenarioLoadError(
            f"ERP fixture is missing: {erp_fixture}"
        )
    selector_profile = None
    if definition.selector_profile:
        selector_profile = (
            source_path.parent / definition.selector_profile
        ).resolve()
        if not selector_profile.is_file():
            raise ScenarioLoadError(
                f"selector profile is missing: {selector_profile}"
            )
        try:
            ERPSelectors.from_file(selector_profile)
        except Exception as error:
            raise ScenarioLoadError(str(error)) from error
    reconciliation_config = None
    if definition.reconciliation_config:
        reconciliation_config = (
            source_path.parent / definition.reconciliation_config
        ).resolve()
        if not reconciliation_config.is_file():
            raise ScenarioLoadError(
                "reconciliation config is missing: "
                f"{reconciliation_config}"
            )
        try:
            ReconciliationConfig.from_file(reconciliation_config)
        except Exception as error:
            raise ScenarioLoadError(str(error)) from error

    return LoadedScenario(
        definition=definition,
        scenario_path=source_path,
        expected_input=expected_input,
        erp_fixture=erp_fixture,
        selector_profile=selector_profile,
        reconciliation_config=reconciliation_config,
    )
