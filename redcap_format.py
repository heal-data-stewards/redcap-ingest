#!/usr/bin/env python3
"""
redcap_format.py

Apply a previously generated JSON map to a quasi-REDCap dictionary, producing
an output workbook that contains the canonical REDCap columns in order. This
script now focuses solely on map application; use `map.py` to build new maps.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

# Canonical REDCap headers – the 16 columns used when normalising output
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


def apply_map(
    source_excel: Path,
    map_json: Path,
    output_excel: Path,
    elide_unlabeled: bool = False,
) -> None:
    """Apply the JSON map to the source workbook and write a canonical XLSX."""

    mapping_cfg = json.loads(map_json.read_text())
    xls = pd.ExcelFile(source_excel)
    result_sheets = []

    for sheet_name in xls.sheet_names:
        cfg = mapping_cfg.get(sheet_name, {})
        if not cfg or cfg.get("ignore", False):
            print(f"⏭️  Skipping sheet '{sheet_name}'")
            continue

        start_row = cfg.get("start_row", 1)
        raw_map = cfg.get("mapping", {})
        immediate = cfg.get("immediate", {})

        df0 = pd.read_excel(source_excel, sheet_name=sheet_name, header=None, dtype=str)
        hdr = df0.iloc[start_row - 1].fillna("").astype(str).tolist()
        data = df0.iloc[start_row:].copy()
        data.columns = hdr
        df2 = data.fillna("")

        rename_map = {raw: canon for canon, raw in raw_map.items()}
        df2 = df2.rename(columns=rename_map)

        for canon, val in immediate.items():
            df2[canon] = val

        for col in ALL:
            if col not in df2.columns:
                df2[col] = ""

        mask = df2["Variable / Field Name"].astype(str).str.strip().ne("")
        if elide_unlabeled:
            mask &= df2["Field Label"].astype(str).str.strip().ne("")

        df2 = df2.loc[mask]
        df2 = df2[ALL]

        result_sheets.append(df2)

    if not result_sheets:
        sys.exit("ERROR: No sheets to write (all were ignored or empty).")

    final_df = pd.concat(result_sheets, ignore_index=True)
    output_excel.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
        final_df.to_excel(writer, index=False, sheet_name="REDCap")

    print(f"Wrote normalized REDCap file with {len(result_sheets)} sheets → {output_excel}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a REDCap mapping JSON")
    parser.add_argument("dict_file", help="Original Excel workbook")
    parser.add_argument("--map", dest="map_file", required=True, help="Path to map JSON")
    parser.add_argument(
        "--output",
        dest="output_file",
        required=True,
        help="Destination XLSX to write",
    )
    parser.add_argument(
        "--elide-unlabeled",
        action="store_true",
        help="Also drop rows lacking a Field Label",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    apply_map(
        source_excel=Path(args.dict_file),
        map_json=Path(args.map_file),
        output_excel=Path(args.output_file),
        elide_unlabeled=args.elide_unlabeled,
    )


if __name__ == "__main__":
    main()
