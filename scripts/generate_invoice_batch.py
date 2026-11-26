#!/usr/bin/env python3
"""Generate deterministic invoice fixtures for stress and demo tests."""

import argparse
import csv
import json
from pathlib import Path


def build_batch(count: int):
    expected = []
    erp = []
    for index in range(1, count + 1):
        invoice_id = f"INV-S{index:04d}"
        customer_id = f"CUST-S{index:04d}"
        amount = f"{100 + index % 900}.00"
        status = "paid" if index % 2 == 0 else "pending"
        expected.append(
            {
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "currency": "CNY",
                "expected_amount": amount,
                "expected_status": status,
                "due_date": "2026-12-31",
            }
        )
        bucket = index % 10
        if bucket == 2:
            continue
        erp_amount = amount
        erp_status = status
        if bucket == 0:
            erp_amount = f"{float(amount) + 5:.2f}"
        elif bucket == 1:
            erp_status = "pending" if status == "paid" else "paid"
        erp.append(
            {
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "currency": "CNY",
                "amount": erp_amount,
                "status": erp_status,
                "due_date": "2026-12-31",
            }
        )
        if bucket == 3:
            erp.append(dict(erp[-1]))
    return expected, erp


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected, erp = build_batch(args.count)

    csv_path = output_dir / "expected.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=list(expected[0]),
        )
        writer.writeheader()
        writer.writerows(expected)

    erp_path = output_dir / "erp.json"
    erp_path.write_text(
        json.dumps({"invoices": erp}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated invoices: {len(expected)}")
    print(f"ERP records: {len(erp)}")
    print(f"CSV: {csv_path}")
    print(f"ERP JSON: {erp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
