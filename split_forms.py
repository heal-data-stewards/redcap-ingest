#!/usr/bin/env python3
"""
split_forms.py

Split a REDCap dictionary workbook into per-form workbooks based on the
"Form Name" column produced by rcmod/fix.py.

Usage:

    python split_forms.py FinalDict.xlsx

By default, new workbooks are written alongside the input file using the
pattern `<basename>-<form>.xlsx`. Files are only created when more than one
distinct form name is present. Rows with a blank/NA form name are logged and
skipped.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

import pandas as pd


def slugify_form_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "form"


def split_forms(input_path: Path, output_dir: Path | None = None) -> List[Path]:
    df = pd.read_excel(input_path)

    if "Form Name" not in df.columns:
        raise SystemExit("ERROR: column 'Form Name' not found in workbook")

    forms = df["Form Name"].fillna("").astype(str).str.strip()
    unique_forms = sorted({name for name in forms if name})

    if len(unique_forms) <= 1:
        print("Only one form detected; no split files created.")
        return []

    base_dir = output_dir or input_path.parent
    base_name = input_path.stem

    output_paths: List[Path] = []
    for form in unique_forms:
        slug = slugify_form_name(form)
        out_path = base_dir / f"{base_name}-{slug}.xlsx"
        subset = df.loc[forms == form].copy()
        if subset.empty:
            continue
        subset.to_excel(out_path, index=False, sheet_name="REDCap")
        print(f"Wrote {len(subset)} rows → {out_path}")
        output_paths.append(out_path)

    blanks = (forms == "").sum()
    if blanks:
        print(f"Warning: {blanks} row(s) with blank 'Form Name' were ignored.")

    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split REDCap dictionary by form")
    parser.add_argument("input", help="Path to the consolidated REDCap workbook")
    parser.add_argument(
        "--output-dir",
        help="Directory to write per-form workbooks (defaults to input directory)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise SystemExit(f"ERROR: input file not found: {input_path}")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    split_forms(input_path, output_dir)


if __name__ == "__main__":
    main()
