#!/usr/bin/env python3
"""
apply_dsl.py

Reads an original REDCap dictionary (.csv/.xlsx), a map.json, and a DSL
operations file, executes the primitives (after renaming raw→canonical
with the map), and writes out a fully compliant REDCap dictionary.

Usage:
    python apply_dsl.py \
        --dict DataDictionary.xlsx \
        --map map.json \
        --ops fixes.rop \
        --output NewDict.xlsx
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

import pandas as pd

VAR_RE = re.compile(r'^[a-z][a-z0-9_]{0,25}$')

def parse_args():
    p = argparse.ArgumentParser(description="Apply DSL operations to REDCap dictionary")
    p.add_argument('--dict',    required=True, help='Original REDCap dictionary file')
    p.add_argument('--map',     required=True, help='map.json with {"fieldname":raw,"override":bool}')
    p.add_argument('--ops',     required=True, help='DSL operations file')
    p.add_argument('--output',  required=True, help='Output corrected dictionary file')
    return p.parse_args()

def load_df(path: Path):
    if path.suffix.lower() == '.csv':
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.read_excel(path, dtype=str).fillna('')

def write_df(df: pd.DataFrame, path: Path):
    suffix = path.suffix.lower()
    if suffix == '.csv':
        df.to_csv(path, index=False)
    elif suffix in ('.xls', '.xlsx'):
        # explicit writer so openpyxl saves cleanly
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
    else:
        raise ValueError(f"Unsupported output format: {suffix}")

class DSLExecutor:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        seen = []
        if 'Variable / Field Name' in df.columns:
            seen = df['Variable / Field Name'].dropna().tolist()
        self.seen_vars = set(seen)

    def EnsureColumn(self, header):
        if header not in self.df.columns:
            self.df[header] = ''

    def RenameColumn(self, raw, canon):
        if raw in self.df.columns and raw != canon:
            self.df.rename(columns={raw: canon}, inplace=True)

    def SetFormName(self, row, formname):
        idx = row - 2
        col = 'Form Name'
        self.EnsureColumn(col)
        self.df.at[idx, col] = formname

    def SetVariableName(self, row, newname):
        idx = row - 2
        base, suffix = newname, 2
        candidate = newname
        while candidate in self.seen_vars:
            candidate = f"{base}_{suffix}"
            suffix += 1
        self.df.at[idx, 'Variable / Field Name'] = candidate
        self.seen_vars.add(candidate)

    def SetFieldType(self, row, ftype):
        idx = row - 2
        self.df.at[idx, 'Field Type'] = ftype

    def SetChoices(self, row, choices):
        idx = row - 2
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        self.df.at[idx, col] = ' | '.join(f"{c},{l}" for c, l in choices)

    def SetSlider(self, row, mn, mn_lbl, mx, mx_lbl):
        idx = row - 2
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        self.df.at[idx, col] = f"{mn},{mn_lbl} | {mx},{mx_lbl}"

    def SetFormula(self, row, formula):
        idx = row - 2
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        self.df.at[idx, col] = formula

    def SetFormat(self, row, fmt):
        idx = row - 2
        col = 'Text Validation Type OR Show Slider Number'
        self.EnsureColumn(col)
        self.df.at[idx, col] = fmt

    def SetValidation(self, row, vtype, vmin, vmax):
        idx = row - 2
        c1 = 'Text Validation Type OR Show Slider Number'
        c2 = 'Text Validation Min'
        c3 = 'Text Validation Max'
        for c in (c1, c2, c3):
            self.EnsureColumn(c)
        self.df.at[idx, c1] = vtype
        self.df.at[idx, c2] = vmin
        self.df.at[idx, c3] = vmax

def parse_call(line: str):
    expr = ast.parse(line, mode='eval').body
    if not isinstance(expr, ast.Call):
        raise ValueError(f"Not a call: {line}")
    name = expr.func.id
    args = []
    for a in expr.args:
        if isinstance(a, ast.Constant):
            args.append(a.value)
        elif isinstance(a, ast.Name):
            # bareword → string
            args.append(a.id)
        else:
            args.append(ast.literal_eval(a))
    return name, args

def main():
    args = parse_args()
    df = load_df(Path(args.dict))

    # apply map.json renames
    mapping = json.loads(Path(args.map).read_text(encoding='utf-8'))
    for canon, info in mapping.items():
        raw = info.get('fieldname')
        if not info.get('override', False) and raw in df.columns:
            df.rename(columns={raw: canon}, inplace=True)

    executor = DSLExecutor(df)

    for raw in Path(args.ops).read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        try:
            cmd, params = parse_call(line)
        except Exception:
            print(f"Skipping invalid DSL line: {line}", file=sys.stderr)
            continue
        fn = getattr(executor, cmd, None)
        if not fn:
            print(f"Unknown primitive: {cmd}", file=sys.stderr)
            continue
        fn(*params)

    write_df(executor.df, Path(args.output))
    print(f"Wrote corrected dictionary to {args.output}")

if __name__ == '__main__':
    main()
