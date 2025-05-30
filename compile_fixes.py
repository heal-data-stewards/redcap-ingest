#!/usr/bin/env python3
"""
generate_dsl.py

Reads the original REDCap dictionary, a map.json, and an augmented report.json
(with inferred_field_type and configuration), and emits a sequence of
primitive DSL commands to transform the original into a fully compliant REDCap
dictionary, including populating the Form Name column.

Usage:
    python generate_dsl.py \
        --dict DataDictionary.xlsx \
        --map map.json \
        --report report.json \
        [--output commands.ops]

Primitives used:
  EnsureColumn(header)
  RenameColumn(rawHeader, canonicalHeader)
  SetFormName(rowNumber, formName)
  SetVariableName(rowNumber, newVariableName)
  SetFieldType(rowNumber, fieldType)
  SetChoices(rowNumber, [(code,label),...])
  SetSlider(rowNumber, min, minLabel, max, maxLabel)
  SetFormula(rowNumber, formulaString)
  SetFormat(rowNumber, formatString)
  SetValidation(rowNumber, validationType, min, max)
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

# regex for valid REDCap variable names
VAR_RE = re.compile(r'^[a-z][a-z0-9_]{0,25}$')

def sanitize_var(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)
    if not s or not s[0].isalpha():
        s = f"var_{s}"
    return s[:26]

def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    parser = argparse.ArgumentParser(
        description="Generate DSL commands from map + inferred report"
    )
    parser.add_argument('--dict',   dest='dict_file',  required=True,
                        help='Original REDCap dictionary (.csv/.xlsx)')
    parser.add_argument('--map',    dest='map_file',   required=True,
                        help='map.json with {"fieldname":..., "override":...}')
    parser.add_argument('--report', dest='report_file',required=True,
                        help='augmented report.json with inferred_field_type & configuration')
    parser.add_argument('-o', '--output', dest='out_file',
                        help='where to write DSL commands (default stdout)')
    args = parser.parse_args()

    # load DataFrame to know row count and raw headers
    if args.dict_file.lower().endswith('.csv'):
        df = pd.read_csv(args.dict_file, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(args.dict_file, dtype=str).fillna('')
    raw_headers = list(df.columns)
    row_count = len(df)

    mapping = load_json(Path(args.map_file))
    report  = load_json(Path(args.report_file))

    cmds = []

    # 1) Ensure all canonical headers exist
    for canon in mapping.keys():
        cmds.append(f'EnsureColumn("{canon}")')

    # 2) Rename raw → canonical where override is false
    for canon, info in mapping.items():
        raw = info.get("fieldname")
        override = info.get("override", False)
        if not override and raw in raw_headers and raw != canon:
            cmds.append(f'RenameColumn("{raw}", "{canon}")')

    # 3) Populate Form Name if override specified
    form_info = mapping.get("Form Name", {})
    if form_info.get("override"):
        form_value = form_info.get("fieldname", "")
        # apply to every data row (rows start at line 2)
        for row in range(2, row_count + 2):
            cmds.append(f'SetFormName({row}, "{form_value}")')

    # 4) Row-level fixes from report
    for entry in report:
        row = entry.get("line")
        inf_type = entry.get("inferred_field_type")
        cfg = entry.get("configuration", {})

        # variable name correction
        orig_var = entry.get("Variable / Field Name", "")
        if not VAR_RE.match(orig_var):
            newvar = sanitize_var(orig_var)
            cmds.append(f'SetVariableName({row}, "{newvar}")')

        # field type
        if inf_type:
            cmds.append(f'SetFieldType({row}, {inf_type})')

        # configuration
        if inf_type in ("radio", "checkbox", "dropdown"):
            choice_items = cfg.get("choices", [])
            pairs = ",".join(
                f'("{item["code"]}","{item["label"]}")'
                for item in choice_items
            )
            cmds.append(f'SetChoices({row}, [{pairs}])')

        elif inf_type == "slider":
            mn     = cfg.get("min")
            mn_lbl = cfg.get("min_label", "")
            mx     = cfg.get("max")
            mx_lbl = cfg.get("max_label", "")
            cmds.append(
                f'SetSlider({row}, {mn}, "{mn_lbl}", {mx}, "{mx_lbl}")'
            )

        elif inf_type == "calc":
            formula = cfg.get("formula", "")
            cmds.append(f'SetFormula({row}, "{formula}")')

        elif inf_type in ("date", "datetime"):
            fmt = cfg.get("format", "")
            cmds.append(f'SetFormat({row}, "{fmt}")')

        elif inf_type == "text":
            vt   = cfg.get("validation_type", "")
            vmin = cfg.get("min", "")
            vmax = cfg.get("max", "")
            cmds.append(
                f'SetValidation({row}, "{vt}", "{vmin}", "{vmax}")'
            )

    output = "\n".join(cmds) + "\n"
    if args.out_file:
        Path(args.out_file).write_text(output, encoding='utf-8')
    else:
        print(output)

if __name__ == '__main__':
    main()
