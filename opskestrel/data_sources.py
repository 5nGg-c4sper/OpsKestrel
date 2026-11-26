"""Load task cases from external data files."""

import csv
from pathlib import Path
from typing import List

from opskestrel.task_models import (
    TaskCaseDefinition,
    TaskDatasetCSVSource,
)


class DataSourceLoadError(ValueError):
    """Raised when a dataset data source cannot be loaded."""


def load_csv_cases(
    source: TaskDatasetCSVSource,
    base_dir,
) -> List[TaskCaseDefinition]:
    """Convert every CSV row into one dataset case."""
    csv_path = (
        Path(base_dir) / source.path.strip()
    ).expanduser().resolve()
    if not csv_path.is_file():
        raise DataSourceLoadError(
            f"CSV data source is missing or not a file: {csv_path}"
        )

    try:
        with csv_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = [
                field.strip()
                for field in (reader.fieldnames or [])
            ]
            if not fieldnames or any(not field for field in fieldnames):
                raise DataSourceLoadError(
                    f"CSV data source has an empty header: {csv_path}"
                )
            if len(set(fieldnames)) != len(fieldnames):
                raise DataSourceLoadError(
                    f"CSV data source has duplicate headers: {csv_path}"
                )
            reader.fieldnames = fieldnames

            case_name_column = source.case_name_column.strip()
            if case_name_column not in fieldnames:
                raise DataSourceLoadError(
                    "CSV case name column is missing: "
                    f"{case_name_column} ({csv_path})"
                )

            parameter_columns = {
                name: column.strip()
                for name, column in source.parameters.items()
            }
            if not parameter_columns:
                parameter_columns = {
                    field: field
                    for field in fieldnames
                    if field != case_name_column
                }
            if not parameter_columns:
                raise DataSourceLoadError(
                    f"CSV data source has no task parameters: {csv_path}"
                )

            missing_columns = sorted(
                set(parameter_columns.values()) - set(fieldnames)
            )
            if missing_columns:
                raise DataSourceLoadError(
                    "CSV parameter columns are missing: "
                    f"{', '.join(missing_columns)} ({csv_path})"
                )

            cases = []
            seen_case_names = set()
            for line_number, row in enumerate(reader, start=2):
                if row.get(None):
                    raise DataSourceLoadError(
                        "CSV row has more values than headers at "
                        f"line {line_number}: {csv_path}"
                    )
                if all(
                    value is None or not value.strip()
                    for value in row.values()
                ):
                    continue

                case_name = (row.get(case_name_column) or "").strip()
                if not case_name:
                    raise DataSourceLoadError(
                        f"CSV case name is empty at line {line_number}: "
                        f"{csv_path}"
                    )
                if case_name in seen_case_names:
                    raise DataSourceLoadError(
                        f"duplicate CSV case name {case_name!r} at "
                        f"line {line_number}: {csv_path}"
                    )
                seen_case_names.add(case_name)

                parameters = {}
                for task_parameter, csv_column in parameter_columns.items():
                    value = row.get(csv_column)
                    if value is None or not value.strip():
                        raise DataSourceLoadError(
                            f"CSV value for {task_parameter!r} is empty "
                            f"at line {line_number}: {csv_path}"
                        )
                    parameters[task_parameter] = value

                cases.append(
                    TaskCaseDefinition(
                        name=case_name,
                        parameters=parameters,
                        attempts=source.attempts,
                        retry_delay_seconds=source.retry_delay_seconds,
                    )
                )
    except OSError as error:
        raise DataSourceLoadError(
            f"failed to read CSV data source {csv_path}: {error}"
        ) from error

    if not cases:
        raise DataSourceLoadError(
            f"CSV data source contains no cases: {csv_path}"
        )
    return cases
