"""Persist operator review decisions for reconciliation differences."""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from soc_agent.operators import OperatorRole
from soc_agent.reconciliation import (
    ReconciliationReport,
    ReconciliationStatus,
)


class ReviewStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"


class ReviewError(ValueError):
    """Raised when a review decision or store is invalid."""


@dataclass(frozen=True)
class ReviewRecord:
    invoice_id: str
    status: ReviewStatus
    reviewer: str
    note: str = ""
    updated_at: datetime = None
    reviewer_role: str = OperatorRole.REVIEWER.value

    def __post_init__(self):
        invoice_id = self.invoice_id.strip()
        reviewer = self.reviewer.strip()
        note = self.note.strip()
        if not invoice_id:
            raise ReviewError("invoice_id must not be empty")
        if not reviewer:
            raise ReviewError("reviewer must not be empty")
        if len(reviewer) > 100:
            raise ReviewError("reviewer must be 100 characters or fewer")
        if len(note) > 2000:
            raise ReviewError("note must be 2000 characters or fewer")
        reviewer_role = OperatorRole(self.reviewer_role)
        object.__setattr__(self, "invoice_id", invoice_id)
        object.__setattr__(self, "reviewer", reviewer)
        object.__setattr__(self, "note", note)
        object.__setattr__(self, "reviewer_role", reviewer_role.value)
        if not isinstance(self.status, ReviewStatus):
            object.__setattr__(self, "status", ReviewStatus(self.status))
        if self.updated_at is None:
            object.__setattr__(
                self,
                "updated_at",
                datetime.now(timezone.utc),
            )

    def to_dict(self) -> Dict:
        return {
            "invoice_id": self.invoice_id,
            "status": self.status.value,
            "reviewer": self.reviewer,
            "reviewer_role": self.reviewer_role,
            "note": self.note,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "ReviewRecord":
        return cls(
            invoice_id=str(payload.get("invoice_id", "")),
            status=ReviewStatus(str(payload.get("status", ""))),
            reviewer=str(payload.get("reviewer", "")),
            note=str(payload.get("note", "")),
            reviewer_role=str(
                payload.get("reviewer_role", OperatorRole.REVIEWER.value)
            ),
            updated_at=(
                datetime.fromisoformat(str(payload["updated_at"]))
                if payload.get("updated_at")
                else None
            ),
        )


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self._records: Dict[str, ReviewRecord] = {}
        self._load()

    @property
    def records(self) -> Mapping[str, ReviewRecord]:
        return dict(self._records)

    def get(self, invoice_id: str) -> Optional[ReviewRecord]:
        return self._records.get(invoice_id.strip().casefold())

    def set(
        self,
        invoice_id: str,
        status,
        reviewer: str,
        note: str = "",
        reviewer_role=OperatorRole.REVIEWER,
        updated_at=None,
    ) -> ReviewRecord:
        record = ReviewRecord(
            invoice_id=invoice_id,
            status=status,
            reviewer=reviewer,
            note=note,
            reviewer_role=reviewer_role,
            updated_at=updated_at,
        )
        return self.put(record)

    def put(self, record: ReviewRecord) -> ReviewRecord:
        self._records[record.invoice_id.casefold()] = record
        self._write()
        return record

    def _replace_records(
        self,
        records: Mapping[str, ReviewRecord],
    ) -> None:
        self._records = dict(records)
        self._write()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ReviewError(
                f"failed to read review store {self.path}: {error}"
            ) from error
        if payload.get("schema_version") != 1:
            raise ReviewError("unsupported review store version")
        reviews = payload.get("reviews")
        if not isinstance(reviews, dict):
            raise ReviewError("review store must contain a reviews object")
        records = {}
        for value in reviews.values():
            if not isinstance(value, dict):
                raise ReviewError("review entries must be objects")
            try:
                record = ReviewRecord.from_dict(value)
            except (ValueError, TypeError) as error:
                raise ReviewError(str(error)) from error
            records[record.invoice_id.casefold()] = record
        self._records = records

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "reviews": {
                key: record.to_dict()
                for key, record in sorted(self._records.items())
            },
        }
        temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)


class ReviewAuditError(ValueError):
    """Raised when the review audit chain is invalid."""


class ReviewAuditLog:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self._events: List[Dict] = []
        self._load()

    @property
    def events(self):
        return tuple(dict(event) for event in self._events)

    def append(
        self,
        invoice_id: str,
        previous_status: Optional[ReviewStatus],
        record: ReviewRecord,
    ) -> Dict:
        previous_hash = (
            self._events[-1]["event_hash"]
            if self._events
            else ""
        )
        payload = {
            "schema_version": 1,
            "sequence": len(self._events) + 1,
            "timestamp": record.updated_at.isoformat(),
            "invoice_id": record.invoice_id,
            "previous_status": (
                previous_status.value if previous_status else None
            ),
            "new_status": record.status.value,
            "reviewer": record.reviewer,
            "reviewer_role": record.reviewer_role,
            "note": record.note,
            "previous_hash": previous_hash,
        }
        payload["event_hash"] = _review_event_hash(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True)
                + "\n"
            )
            audit_file.flush()
            os.fsync(audit_file.fileno())
        self._events.append(payload)
        return dict(payload)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ReviewAuditError(
                f"failed to read review audit log: {error}"
            ) from error
        events = []
        previous_hash = ""
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ReviewAuditError(
                    f"invalid audit event at line {line_number}: {error}"
                ) from error
            if payload.get("schema_version") != 1:
                raise ReviewAuditError(
                    f"unsupported audit event at line {line_number}"
                )
            if payload.get("sequence") != len(events) + 1:
                raise ReviewAuditError(
                    f"invalid audit sequence at line {line_number}"
                )
            if payload.get("previous_hash") != previous_hash:
                raise ReviewAuditError(
                    f"broken audit hash chain at line {line_number}"
                )
            expected_hash = _review_event_hash(payload)
            if payload.get("event_hash") != expected_hash:
                raise ReviewAuditError(
                    f"audit event hash mismatch at line {line_number}"
                )
            previous_hash = payload["event_hash"]
            events.append(payload)
        self._events = events


def _review_event_hash(payload: Mapping) -> str:
    canonical = {
        key: value
        for key, value in payload.items()
        if key != "event_hash"
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_review_summary(
    report: ReconciliationReport,
    records: Mapping[str, ReviewRecord],
) -> Dict:
    difference_ids = [
        result.invoice_id
        for result in report.results
        if result.status != ReconciliationStatus.MATCHED
    ]
    pending = 0
    confirmed = 0
    false_positive = 0
    for invoice_id in difference_ids:
        record = records.get(invoice_id.casefold())
        status = record.status if record else ReviewStatus.PENDING
        if status == ReviewStatus.CONFIRMED:
            confirmed += 1
        elif status == ReviewStatus.FALSE_POSITIVE:
            false_positive += 1
        else:
            pending += 1
    reviewed = confirmed + false_positive
    return {
        "total_differences": len(difference_ids),
        "pending": pending,
        "confirmed": confirmed,
        "false_positive": false_positive,
        "reviewed": reviewed,
        "all_reviewed": (
            bool(difference_ids) and reviewed == len(difference_ids)
        ),
    }


def review_payload(record: Optional[ReviewRecord]) -> Dict:
    if record is None:
        return {
            "status": ReviewStatus.PENDING.value,
            "reviewer": None,
            "reviewer_role": None,
            "note": "",
            "updated_at": None,
        }
    return record.to_dict()


def apply_reviews_to_payload(
    payload: Mapping,
    records: Mapping[str, ReviewRecord],
) -> Dict:
    updated = json.loads(json.dumps(payload))
    reconciliation = ReconciliationReport.from_dict(
        updated["reconciliation"]
    )
    for result in updated["reconciliation"]["results"]:
        if result.get("status") == ReconciliationStatus.MATCHED.value:
            result.pop("review", None)
            continue
        result["review"] = review_payload(
            records.get(str(result["invoice_id"]).casefold())
        )
    updated["review_summary"] = build_review_summary(
        reconciliation,
        records,
    )
    return updated
