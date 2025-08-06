#!/usr/bin/env python3
"""
redcap_lint.py – v0.15
~~~~~~~~~~~~~~~~~~~~~~
Lint a REDCap data-dictionary that already uses canonical REDCap headers.

• Checks every row for common issues (invalid / duplicate variable names, bad
  field types, missing choices for multi-choice fields).
• Prints a summary to stdout and can write a detailed JSON report with
  --report.
• Optionally overrides the entire “Form Name” column with --form-name.

Usage
-----

    python redcap_lint.py DataDictionary.xlsx \
        --report lint_report.json \
        --form-name baseline_survey
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import pandas as pd

# ───────────────────────── Canonical REDCap headers
REQ = [
    "Variable / Field Name",
    "Form Name",
    "Field Type",
    "Field Label",
]
OPT = [
    "Section Header",
    "Choices, Calculations, OR Slider Labels",
    "Field Note",
    "Text Validation Type OR Show Slider Number",
    "Text Validation Min",
    "Text Validation Max",
    "Identifier?",
    "Branching Logic",
    "Required Field?",
    "Custom Alignment",
    "Question Number (surveys only)",
    "Field Annotation",
]
ALL = REQ + OPT

FIELD_TYPES: Set[str] = {
    "text", "notes", "radio", "checkbox", "dropdown", "calc", "file",
    "yesno", "truefalse", "slider", "descriptive", "date", "datetime",
}

VAR_RE = re.compile(r"^[a-z][a-z0-9_]{0,25}$")
CHOICE_COL = "Choices, Calculations, OR Slider Labels"
_VALIDATION_TYPES = {
    "integer", "number", "date_mdy", "date_dmy", "time",
    "datetime_mdy", "datetime_dmy", "email", "phone",
}
_YN = {"y", "n", "yes", "no", "true", "false"}


# ────────────────────────── helpers
def load_dict(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str).fillna("")
    if path.suffix.lower() in {".xls", ".xlsx"}:
        return pd.read_excel(path, dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {path.suffix}")


# ────────────────────────── linting
def classify_row(row: pd.Series, seen: set[str]) -> tuple[str, List[str]]:
    if (row == "").all():
        return "IGNORE", ["blank line"]
    if str(row.iloc[0]).lstrip().startswith("#"):
        return "IGNORE", ["comment"]

    reasons: List[str] = []

    var = row.get("Variable / Field Name", "").strip()
    if not VAR_RE.match(var):
        reasons.append("invalid variable name")
    elif var in seen:
        reasons.append("duplicate variable name")
    else:
        seen.add(var)

    ftype = row.get("Field Type", "").strip().lower()
    if ftype and ftype not in FIELD_TYPES:
        reasons.append(f"unknown field type '{ftype}'")
    if ftype in {"radio", "checkbox", "dropdown"} and not row.get(CHOICE_COL, "").strip():
        reasons.append("missing choices for multi-choice field")

    return ("ACCEPT" if not reasons else "VIOLATE"), reasons


def lint_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for i, row in df.iterrows():
        cls, why = classify_row(row, seen)
        valid = cls == "ACCEPT"
        error = None if valid else "; ".join(why)

        records.append(
            {
                "line": i + 2,  # +2 because Excel rows are 1-indexed and header is row 1
                "classification": {"valid": valid, "error": error},
                "Variable / Field Name": row.get("Variable / Field Name", ""),
                "Form Name": row.get("Form Name", ""),
                "Field Type": row.get("Field Type", ""),
                "Field Label": row.get("Field Label", ""),
                CHOICE_COL: row.get(CHOICE_COL, ""),
            }
        )
    return records


def print_summary(records: List[Dict[str, Any]]) -> None:
    cnt = {"ACCEPT": 0, "VIOLATE": 0}
    for rec in records:
        if rec["classification"]["valid"]:
            cnt["ACCEPT"] += 1
        else:
            cnt["VIOLATE"] += 1
    print("\nLint Summary\n============")
    print(f"ACCEPT  : {cnt['ACCEPT']}")
    print(f"VIOLATE : {cnt['VIOLATE']}")
    print("============\n")


# ────────────────────────── CLI
def main() -> None:
    parser = argparse.ArgumentParser(description="Lint a REDCap data dictionary.")
    parser.add_argument("dict_file", help="Path to REDCap data dictionary (CSV/XLS/XLSX)")
    parser.add_argument(
        "--report",
        dest="report_file",
        help="Write detailed JSON lint report to this path",
        default=None,
    )
    parser.add_argument(
        "--form-name",
        dest="form_name",
        help="Override every value in the 'Form Name' column",
        default=None,
    )
    args = parser.parse_args()

    dict_path = Path(args.dict_file)
    report_path = Path(args.report_file) if args.report_file else None

    if not dict_path.is_file():
        sys.exit(f"ERROR: dictionary file not found: {dict_path}")

    # Load and validate basic header presence
    try:
        df = load_dict(dict_path)
    except Exception as exc:
        sys.exit(f"ERROR loading dictionary: {exc}")

    if args.form_name is not None:
        df["Form Name"] = args.form_name

    missing = [c for c in REQ if c not in df.columns]
    if missing:
        sys.exit(f"ERROR: missing required columns: {', '.join(missing)}")

    # Lint
    records = lint_dataframe(df)
    print_summary(records)

    # Optional JSON report
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"Report written to {report_path}")

    # Non-zero exit if any violations
    if any(not rec["classification"]["valid"] for rec in records):
        sys.exit(2)


if __name__ == "__main__":
    main()
