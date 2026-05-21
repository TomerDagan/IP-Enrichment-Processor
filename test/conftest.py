from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pytest


def _pretty_case_name(test_name: str) -> str:
    name = test_name
    if name.startswith("test_"):
        name = name[len("test_") :]
    return name.replace("_", " ").strip().capitalize()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--readable-report",
        action="store",
        default="output/test_report.md",
        help="Path for a human-readable markdown test report.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config._readable_case_results = []  # type: ignore[attr-defined]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()

    if report.when != "call":
        return

    explanation = ""
    test_func = getattr(item, "function", None)
    if test_func and test_func.__doc__:
        explanation = test_func.__doc__.strip()
    if not explanation:
        explanation = _pretty_case_name(item.name)

    class_name = ""
    if hasattr(item, "cls") and item.cls is not None:
        class_name = item.cls.__name__

    case_result: Dict[str, str] = {
        "nodeid": item.nodeid,
        "class_name": class_name,
        "case_name": item.name,
        "scenario": explanation,
        "status": report.outcome.upper(),
    }
    item.config._readable_case_results.append(case_result)  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    report_path = session.config.getoption("--readable-report")
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, str]] = session.config._readable_case_results  # type: ignore[attr-defined]
    passed = sum(1 for r in results if r["status"] == "PASSED")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    skipped = sum(1 for r in results if r["status"] == "SKIPPED")

    lines = [
        "# Unit Test Readable Report",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"Total tests: {len(results)}",
        f"Passed: {passed}",
        f"Failed: {failed}",
        f"Skipped: {skipped}",
        f"Pytest exit status: {exitstatus}",
        "",
        "## Scenario Results",
        "",
        "| Status | Group | Test | Scenario |",
        "|---|---|---|---|",
    ]

    for r in results:
        group = r["class_name"] if r["class_name"] else "(module)"
        lines.append(
            f"| {r['status']} | {group} | {r['case_name']} | {r['scenario']} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This file is generated automatically after each pytest run.",
            "- Use --readable-report <path> to change its output location.",
        ]
    )

    report_file.write_text("\n".join(lines), encoding="utf-8")