#!/usr/bin/env python3
"""
compile_fixes.py

Reads the original REDCap dictionary, map.json, and an augmented report.json
(with inferred_field_type and configuration), then emits a DSL script (.rop)
including ClearCell() primitives for text fields, and always ensures that
the “Section Header” column exists.

Usage:
    python compile_fixes.py \
      --dict DataDictionary.xlsx \
      --map map.json \
      --report augmented_report.json \
      [--output fixes.rop]
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

# Canonical headers (map.json keys) plus optional “Section Header”
CANONICAL_HEADERS = [
    "Variable / Field Name",
    "Form Name",
    "Field Type",
    "Field Label",
    "Choices, Calculations, OR Slider Labels",
    "Section Header",
    "Section Header",  # ensure present
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

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    parser = argparse.ArgumentParser(
        description="Compile DSL primitives from augmented report.json and map.json"
    )
    parser.add_argument(
        "--dict", dest="dict_file", required=True,
        help="Original REDCap dictionary (.csv or .xlsx)"
    )
    parser.add_argument(
        "--map", dest="map_file", required=True,
        help="map.json with {\"fieldname\":..., \"override\":...}"
    )
    parser.add_argument(
        "--report", dest="report_file", required=True,
        help="Augmented report.json with inferred_field_type & configuration"
    )
    parser.add_argument(
        "-o", "--output", dest="out_file",
        help="Path to write DSL commands (defaults to stdout)"
    )
    args = parser.parse_args()

    # Load original to know raw headers
    if args.dict_file.lower().endswith(".csv"):
        df = pd.read_csv(args.dict_file, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(args.dict_file, dtype=str).fillna("")
    raw_headers = list(df.columns)

    # Load map and report
    mapping = load_json(Path(args.map_file))
    report  = load_json(Path(args.report_file))

    ops = []

    # 1) Ensure Section Header exists, then all canonical headers
    ops.append('EnsureColumn("Section Header")')
    for header in mapping.keys():
        ops.append(f'EnsureColumn("{header}")')

    # 2) Rename raw → canonical where override is false
    for canon, info in mapping.items():
        raw = info.get("fieldname")
        override = info.get("override", False)
        if not override and raw in raw_headers and raw != canon:
            ops.append(f'RenameColumn("{raw}", "{canon}")')

    # 3) Populate Form Name if override
    form_info = mapping.get("Form Name", {})
    if form_info.get("override", False):
        form_value = form_info.get("fieldname", "")
        for row_idx in range(2, len(df) + 2):
            ops.append(f'SetFormName({row_idx}, "{form_value}")')

    # 4) Row-level fixes
    VAR_RE = re.compile(r'^[a-z][a-z0-9_]{0,25}$')
    for entry in report:
        row = entry.get("line")
        inf_type = entry.get("inferred_field_type")
        cfg = entry.get("configuration", {})

        # Variable name correction
        orig_var = entry.get("Variable / Field Name", "")
        if not VAR_RE.match(orig_var):
            newvar = entry.get("inferred_variable_name", "")
            if newvar:
                ops.append(f'SetVariableName({row}, "{newvar}")')

        # Field type
        if inf_type:
            ops.append(f'SetFieldType({row}, {inf_type})')

        # Choices for yesno/truefalse
        if inf_type in ("yesno", "truefalse"):
            choices = cfg if isinstance(cfg, list) else []
            if not choices:
                choices = [{"code":"1","label":"Yes"},{"code":"0","label":"No"}]
            pairs = ",".join(f'("{c["code"]}","{c["label"]}")' for c in choices)
            ops.append(f'SetChoices({row}, [{pairs}])')
        # Choices for radio/checkbox/dropdown
        elif inf_type in ("radio", "checkbox", "dropdown"):
            choices = cfg.get("choices", [])
            pairs = ",".join(
                f'("{item["code"]}","{item["label"]}")' for item in choices
            )
            ops.append(f'SetChoices({row}, [{pairs}])')
        # Slider
        elif inf_type == "slider":
            mn = cfg.get("min")
            mn_lbl = cfg.get("min_label","")
            mx = cfg.get("max")
            mx_lbl = cfg.get("max_label","")
            ops.append(f'SetSlider({row}, {mn}, "{mn_lbl}", {mx}, "{mx_lbl}")')
        # Calc
        elif inf_type == "calc":
            formula = cfg.get("formula","")
            ops.append(f'SetFormula({row}, "{formula}")')
        # Date/datetime
        elif inf_type in ("date","datetime"):
            fmt = cfg.get("format","")
            ops.append(f'SetFormat({row}, "{fmt}")')
        # Text: set validation then clear choices
        elif inf_type == "text":
            vt = cfg.get("validation_type","")
            vmin = cfg.get("min","")
            vmax = cfg.get("max","")
            ops.append(f'SetValidation({row}, "{vt}", "{vmin}", "{vmax}")')
            ops.append(f'ClearCell({row}, "Choices, Calculations, OR Slider Labels")')

    # Write ops
    script = "\n".join(ops) + "\n"
    if args.out_file:
        Path(args.out_file).write_text(script, encoding="utf-8")
    else:
        print(script)

if __name__ == "__main__":
    main()
