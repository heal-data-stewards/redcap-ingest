#!/usr/bin/env python3
"""
compile_fixes.py

Reads the original REDCap dictionary and an augmented report.json
(with inferred_field_type and configuration), then emits a DSL script (.rop)
including ClearCell() primitives for text fields, and always ensures that
the "Section Header" column exists.

Usage:
    python compile_fixes.py \
      --dict DataDictionary.xlsx \
      --report augmented_report.json \
      [--output fixes.rop]
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    parser = argparse.ArgumentParser(
        description="Compile DSL primitives from augmented report.json"
    )
    parser.add_argument(
        "--dict", dest="dict_file", required=True,
        help="Original REDCap dictionary (.csv or .xlsx)"
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

    # Load original to know row count
    if args.dict_file.lower().endswith(".csv"):
        df = pd.read_csv(args.dict_file, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(args.dict_file, dtype=str).fillna("")

    report = load_json(Path(args.report_file))

    ops = []

    # 0) Load the REDCap sheet, starting at row 2
    ops.append('ProcessSheet("REDCap", 2)')

    # 1) Always ensure "Section Header" exists
    ops.append('EnsureColumn("Section Header")')

    # 2) Row-level fixes based on your augmented report
    VAR_RE = re.compile(r'^[a-z][a-z0-9_]{0,25}$')
    for entry in report:
        row = entry.get("line")
        inf_type = entry.get("inferred_field_type")
        cfg = entry.get("configuration", {})

        # Variable name correction
        orig_var = entry.get("Variable / Field Name", "")
        if not VAR_RE.match(orig_var):
            lowered = orig_var.lower()
            if orig_var and lowered != orig_var and VAR_RE.match(lowered):
                ops.append(f'LowercaseVariableName({row})')
            else:
                newvar = entry.get("inferred_variable_name", "")
                if newvar:
                    ops.append(f'SetVariableName({row}, "{newvar}")')

        # Field type
        if inf_type:
            ops.append(f'SetFieldType({row}, {inf_type})')

        # yesno / truefalse choices
        if inf_type in ("yesno", "truefalse"):
            choices = cfg if isinstance(cfg, list) else []
            if not choices:
                choices = [{"code":"1","label":"Yes"},{"code":"0","label":"No"}]
            pairs = ",".join(f'("{c["code"]}","{c["label"]}")' for c in choices)
            ops.append(f'SetChoices({row}, [{pairs}])')

        # radio / checkbox / dropdown
        elif inf_type in ("radio", "checkbox", "dropdown"):
            choices = cfg.get("choices", [])
            pairs = ",".join(
                f'("{item["code"]}","{item["label"]}")' for item in choices
            )
            ops.append(f'SetChoices({row}, [{pairs}])')

        # slider
        elif inf_type == "slider":
            mn   = cfg.get("min")
            mn_l = cfg.get("min_label", "")
            mx   = cfg.get("max")
            mx_l = cfg.get("max_label", "")
            ops.append(f'SetSlider({row}, {mn}, "{mn_l}", {mx}, "{mx_l}")')

        # calculation
        elif inf_type == "calc":
            formula = cfg.get("formula", "")
            ops.append(f'SetFormula({row}, "{formula}")')

        # date / datetime formatting
        elif inf_type in ("date", "datetime"):
            fmt = cfg.get("format", "")
            ops.append(f'SetFormat({row}, "{fmt}")')

        # text fields: validation + clear any leftover choices
        elif inf_type == "text":
            vt   = cfg.get("validation_type", "")
            vmin = cfg.get("min", "")
            vmax = cfg.get("max", "")
            ops.append(f'SetValidation({row}, "{vt}", "{vmin}", "{vmax}")')
            ops.append(
                f'ClearCell({row}, "Choices, Calculations, OR Slider Labels")'
            )

    # 3) Write out the DSL script
    script = "\n".join(ops) + "\n"
    if args.out_file:
        Path(args.out_file).write_text(script, encoding="utf-8")
    else:
        print(script)

if __name__ == "__main__":
    main()
