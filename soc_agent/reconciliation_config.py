"""Field mappings and normalization rules for invoice reconciliation."""

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union


class ReconciliationConfigError(ValueError):
    """Raised when reconciliation mapping configuration is invalid."""


CANONICAL_FIELDS = (
    "invoice_id",
    "customer_id",
    "currency",
    "amount",
    "status",
    "due_date",
)

DEFAULT_EXPECTED_COLUMNS = {
    "invoice_id": "invoice_id",
    "customer_id": "customer_id",
    "currency": "currency",
    "amount": "expected_amount",
    "status": "expected_status",
    "due_date": "due_date",
}

DEFAULT_ERP_FIELDS = {
    name: name
    for name in CANONICAL_FIELDS
}


@dataclass(frozen=True)
class ReconciliationConfig:
    expected_columns: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_EXPECTED_COLUMNS)
    )
    erp_fields: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_ERP_FIELDS)
    )
    status_aliases: Dict[str, str] = field(default_factory=dict)
    currency_aliases: Dict[str, str] = field(default_factory=dict)
    amount_tolerance: Decimal = Decimal("0.01")

    def __post_init__(self):
        expected = dict(DEFAULT_EXPECTED_COLUMNS)
        expected.update(self.expected_columns or {})
        erp = dict(DEFAULT_ERP_FIELDS)
        erp.update(self.erp_fields or {})
        self._validate_mapping(expected, "expected_columns")
        self._validate_mapping(erp, "erp_fields")
        try:
            tolerance = Decimal(str(self.amount_tolerance))
        except InvalidOperation as error:
            raise ReconciliationConfigError(
                "amount_tolerance must be a decimal"
            ) from error
        if not tolerance.is_finite() or tolerance < 0:
            raise ReconciliationConfigError(
                "amount_tolerance must be a non-negative decimal"
            )
        object.__setattr__(self, "expected_columns", expected)
        object.__setattr__(self, "erp_fields", erp)
        object.__setattr__(
            self,
            "status_aliases",
            self._normalized_aliases(
                self.status_aliases,
                "status_aliases",
            ),
        )
        object.__setattr__(
            self,
            "currency_aliases",
            {
                key: value.upper()
                for key, value in self._normalized_aliases(
                    self.currency_aliases,
                    "currency_aliases",
                ).items()
            },
        )
        object.__setattr__(self, "amount_tolerance", tolerance)

    @classmethod
    def from_file(
        cls,
        path: Union[str, Path],
    ) -> "ReconciliationConfig":
        source_path = Path(path).expanduser().resolve()
        try:
            payload = json.loads(
                source_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ReconciliationConfigError(
                f"failed to load reconciliation config {source_path}: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise ReconciliationConfigError(
                "reconciliation config must be a JSON object"
            )
        allowed = {
            "expected_columns",
            "erp_fields",
            "status_aliases",
            "currency_aliases",
            "amount_tolerance",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ReconciliationConfigError(
                "unknown reconciliation config fields: "
                + ", ".join(unknown)
            )
        return cls(
            expected_columns=payload.get("expected_columns", {}),
            erp_fields=payload.get("erp_fields", {}),
            status_aliases=payload.get("status_aliases", {}),
            currency_aliases=payload.get("currency_aliases", {}),
            amount_tolerance=payload.get(
                "amount_tolerance",
                "0.01",
            ),
        )

    def map_expected_row(
        self,
        row: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return self._map_row(
            row,
            self.expected_columns,
            amount_key="expected_amount",
            status_key="expected_status",
        )

    def map_erp_row(
        self,
        row: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return self._map_row(
            row,
            self.erp_fields,
            amount_key="amount",
            status_key="status",
        )

    def map_expected_rows(self, rows):
        return [self.map_expected_row(row) for row in rows]

    def map_erp_rows(self, rows):
        return [self.map_erp_row(row) for row in rows]

    def fingerprint(self) -> str:
        payload = {
            "expected_columns": self.expected_columns,
            "erp_fields": self.erp_fields,
            "status_aliases": self.status_aliases,
            "currency_aliases": self.currency_aliases,
            "amount_tolerance": str(self.amount_tolerance),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _map_row(
        self,
        row: Mapping[str, Any],
        mapping: Mapping[str, str],
        amount_key: str,
        status_key: str,
    ) -> Dict[str, Any]:
        values = {
            canonical: row.get(source)
            for canonical, source in mapping.items()
        }
        currency = values.get("currency")
        if currency is not None:
            values["currency"] = self.currency_aliases.get(
                str(currency).strip().casefold(),
                str(currency).strip().upper(),
            )
        status = values.get("status")
        if status is not None:
            values["status"] = self.status_aliases.get(
                str(status).strip().casefold(),
                str(status).strip(),
            )
        return {
            "invoice_id": values.get("invoice_id"),
            "customer_id": values.get("customer_id"),
            "currency": values.get("currency"),
            amount_key: values.get("amount"),
            status_key: values.get("status"),
            "due_date": values.get("due_date"),
        }

    @staticmethod
    def _validate_mapping(mapping, name):
        missing = sorted(set(CANONICAL_FIELDS) - set(mapping))
        unknown = sorted(set(mapping) - set(CANONICAL_FIELDS))
        if missing:
            raise ReconciliationConfigError(
                f"{name} missing fields: {', '.join(missing)}"
            )
        if unknown:
            raise ReconciliationConfigError(
                f"{name} unknown fields: {', '.join(unknown)}"
            )
        if any(not str(value).strip() for value in mapping.values()):
            raise ReconciliationConfigError(
                f"{name} source columns must not be empty"
            )

    @staticmethod
    def _normalized_aliases(values, name):
        if values is None:
            return {}
        if not isinstance(values, dict):
            raise ReconciliationConfigError(f"{name} must be an object")
        normalized = {}
        for key, value in values.items():
            source = str(key).strip()
            target = str(value).strip()
            if not source or not target:
                raise ReconciliationConfigError(
                    f"{name} keys and values must not be empty"
                )
            normalized[source.casefold()] = target
        return normalized
