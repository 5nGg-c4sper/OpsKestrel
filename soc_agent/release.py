"""Release-readiness checks that do not require a desktop session."""

import importlib
import os
import sys
import tempfile
from pathlib import Path

from soc_agent import __version__
from soc_agent.reconciliation import reconcile_files
from soc_agent.reconciliation_config import ReconciliationConfig
from soc_agent.scenarios import load_scenario


def run_release_checks(project_root=None):
    root = Path(
        project_root or Path(__file__).resolve().parents[1]
    ).expanduser().resolve()
    checks = []

    def record(name, passed, detail, warning=False):
        checks.append(
            {
                "name": name,
                "status": (
                    "warning"
                    if warning and not passed
                    else ("passed" if passed else "failed")
                ),
                "detail": detail,
            }
        )

    record(
        "python_version",
        (3, 9) <= sys.version_info[:2] < (3, 13),
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
    for module_name in (
        "pydantic",
        "dotenv",
        "openpyxl",
        "pypdf",
        "reportlab",
    ):
        try:
            importlib.import_module(module_name)
        except Exception as error:
            record(
                f"dependency:{module_name}",
                False,
                str(error),
            )
        else:
            record(
                f"dependency:{module_name}",
                True,
                "imported",
            )

    try:
        importlib.import_module("playwright")
    except Exception as error:
        record(
            "browser_dependency:playwright",
            False,
            str(error),
            warning=True,
        )
    else:
        record(
            "browser_dependency:playwright",
            True,
            "imported",
        )

    required_files = (
        root / "setup.py",
        root / "requirements.txt",
        root / "scenarios/invoice_reconciliation/scenario.json",
        root / "tasks/calculator_parameterized.json",
    )
    for path in required_files:
        record(
            f"file:{path.relative_to(root)}",
            path.is_file(),
            str(path),
        )

    for scenario_path in (
        root / "scenarios/invoice_reconciliation/scenario.json",
        root / "scenarios/customer_followup/scenario.json",
    ):
        try:
            load_scenario(scenario_path)
        except Exception as error:
            record(
                f"scenario:{scenario_path.parent.name}",
                False,
                str(error),
            )
        else:
            record(
                f"scenario:{scenario_path.parent.name}",
                True,
                "validated",
            )

    try:
        report = reconcile_files(
            root
            / "scenarios/invoice_reconciliation/data/input_invoices.csv",
            root
            / "scenarios/invoice_reconciliation/data/erp_invoices.json",
            config=ReconciliationConfig.from_file(
                root / "scenarios/invoice_reconciliation/mapping.json"
            ),
        )
        summary = report.summary
        passed = (
            summary["total"] == 20
            and summary["by_status"]["matched"] == 10
            and summary["by_status"]["invalid_input"] == 3
        )
        detail = (
            f"total={summary['total']}, "
            f"matched={summary['by_status']['matched']}, "
            f"invalid={summary['by_status']['invalid_input']}"
        )
    except Exception as error:
        passed = False
        detail = str(error)
    record("fixture_reconciliation", passed, detail)

    try:
        setup_text = (root / "setup.py").read_text(encoding="utf-8")
        passed = (
            "soc-agent=soc_agent.cli:main" in setup_text
            and "operate=operate.main:main_entry" in setup_text
        )
    except OSError as error:
        passed = False
        setup_text = ""
        detail = str(error)
    else:
        detail = "soc-agent and operate entry points"
    record("entry_points", passed, detail)

    try:
        ignore_text = (root / ".gitignore").read_text(encoding="utf-8")
    except OSError:
        ignore_text = ""
    record(
        "env_ignored",
        any(
            line.strip() == ".env"
            for line in ignore_text.splitlines()
        ),
        ".env must never be committed",
    )
    record(
        "operator_token",
        bool(os.getenv("SOC_OPERATOR_TOKEN")),
        "set SOC_OPERATOR_TOKEN before interview use",
        warning=True,
    )

    try:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            writable = probe.read_text(encoding="utf-8") == "ok"
    except OSError as error:
        writable = False
        detail = str(error)
    else:
        detail = "temporary reports directory writable"
    record("reports_writable", writable, detail)

    failed = [
        check for check in checks if check["status"] == "failed"
    ]
    warnings = [
        check for check in checks if check["status"] == "warning"
    ]
    return {
        "version": __version__,
        "ready": not failed,
        "summary": {
            "total": len(checks),
            "passed": sum(
                check["status"] == "passed" for check in checks
            ),
            "failed": len(failed),
            "warnings": len(warnings),
        },
        "checks": checks,
    }
