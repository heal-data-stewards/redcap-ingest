#!/usr/bin/env python3
"""
generate_dsl.py

Reads the original REDCap dictionary, a map.json, and an augmented report.json
(with inferred_field_type and configuration), and emits a sequence of
primitive DSL commands to transform the original into a fully compliant REDCap
dictionary.

Usage:
    python generate_dsl.py \
        --dict DataDictionary.xlsx \
        --map map.json \
        --report report.json \
        [--output commands.ops]

Primitives used:
  EnsureColumn(header)
  RenameColumn(rawHeader, canonicalHeader)
  SetVariableName(row, newName)
  SetFieldType(row, fieldType)
  SetChoices(row, [(code,label),...])
  SetSlider(row, min, minLabel, max, maxLabel)
  SetFormula(row, formula)
  SetFormat(row, formatString)
  SetValidation(row, validationType, min, max)
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

# VAR name sanitization regex
VAR_RE = re.compile(r'^[a-z][a-z0-9_]{0,25}$')

def sanitize_var(name: str) -> str:
    s = name.strip().lower()
    # replace invalid chars with underscore
    s = re.sub(r'[^a-z0-9_]', '_', s)
    # ensure starts with letter
    if not s or not s[0].isalpha():
        s = f"var_{s}"
    # truncate
    return s[:26]

def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    p = argparse.ArgumentParser(
        description="Generate DSL commands from map + inferred report"
    )
    p.add_argument('--dict', dest='dict_file', required=True,
                   help='Original REDCap dictionary (.csv/.xlsx)')
    p.add_argument('--map', dest='map_file', required=True,
                   help='map.json with {"fieldname":..., "override":...}')
    p.add_argument('--report', dest='report_file', required=True,
                   help='augmented report.json with inferred_field_type & configuration')
    p.add_argument('--output', '-o', dest='out_file',
                   help='where to write DSL commands (default stdout)')
    args = p.parse_args()

    # load original headers
    df = pd.read_csv(args.dict_file, dtype=str, keep_default_na=False) \
         if args.dict_file.lower().endswith('.csv') \
         else pd.read_excel(args.dict_file, dtype=str).fillna('')
    raw_headers = list(df.columns)

    # load map and report
    mapping = load_json(Path(args.map_file))
    report = load_json(Path(args.report_file))

    cmds = []

    # 1) Ensure all canonical headers exist
    for canon in mapping.keys():
        cmds.append(f'EnsureColumn("{canon}")')

    # 2) Rename raw → canonical where override is false
    # map.json: { canonical: {fieldname: raw, override: bool} }
    for canon, info in mapping.items():
        raw = info.get("fieldname")
        override = info.get("override", False)
        if not override and raw in raw_headers and raw != canon:
            cmds.append(f'RenameColumn("{raw}", "{canon}")')

    # 3) Row-level fixes from report
    for entry in report:
        row = entry.get("line")  # 1-based sheet line
        inf_type = entry.get("inferred_field_type")
        cfg = entry.get("configuration", {})

        # variable name fix if invalid or duplicate
        orig_var = entry.get("Variable / Field Name","")
        if not VAR_RE.match(orig_var):
            newvar = sanitize_var(orig_var)
            cmds.append(f'SetVariableName({row}, "{newvar}")')

        # field type
        if inf_type:
            cmds.append(f'SetFieldType({row}, {inf_type})')

        # configuration per type
        if inf_type in ("radio","checkbox","dropdown"):
            choices = cfg.get("choices",[])
            pairs = ",".join(
                f'("{c}","{l}")' for c,l in choices
            )
            cmds.append(f'SetChoices({row}, [{pairs}])')

        elif inf_type == "slider":
            cmds.append(
                f'SetSlider({row}, {cfg.get("min")}, "{cfg.get("min_label","")}", '
                f'{cfg.get("max")}, "{cfg.get("max_label","")}")'
            )

        elif inf_type == "calc":
            formula = cfg.get("formula","")
            cmds.append(f'SetFormula({row}, "{formula}")')

        elif inf_type in ("date","datetime"):
            fmt = cfg.get("format","")
            cmds.append(f'SetFormat({row}, "{fmt}")')

        elif inf_type == "text":
            vt = cfg.get("validation_type","")
            vmin = cfg.get("min","")
            vmax = cfg.get("max","")
            cmds.append(
                f'SetValidation({row}, "{vt}", "{vmin}", "{vmax}")'
            )

        # yesno, truefalse, notes, file, descriptive → no extra

    # write output
    out = Path(args.out_file) if args.out_file else None
    if out:
        out.write_text("\n".join(cmds)+"\n", encoding='utf-8')
    else:
        sys.stdout.write("\n".join(cmds))

if __name__ == "__main__":
    main()
