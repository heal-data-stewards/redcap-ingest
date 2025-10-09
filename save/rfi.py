#!/usr/bin/env python3
"""
apply_dsl.py

Reads an original REDCap dictionary workbook (XLS/XLSX), a map.json, and a DSL
operations file, executes the primitives (including the new multi‐sheet ones),
and writes out a consolidated output sheet.

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

MAX_VAR_NAME_LEN = 100  # REDCap allows up to 100 characters (≤26 recommended).

VAR_RE = re.compile(fr'^[a-z][a-z0-9_]{{0,{MAX_VAR_NAME_LEN - 1}}}$')


def parse_args():
    p = argparse.ArgumentParser(description="Apply DSL operations to REDCap dictionary")
    p.add_argument('--dict',    required=True, help='Original REDCap dictionary file (XLS/XLSX or CSV)')
    p.add_argument('--map',     required=True, help='map.json with {"fieldname":raw,"override":bool}')
    p.add_argument('--ops',     required=True, help='DSL operations file')
    p.add_argument('--output',  required=True, help='Output corrected dictionary file')
    return p.parse_args()


class DSLExecutor:
    def __init__(self, excel_file: pd.ExcelFile, mapping: dict):
        # For multi‐sheet input
        self.excel = excel_file
        # map.json info for default renames
        self.map = mapping

        # Output buffer
        self.output_sheet_name = None
        self.output_df = None

        # Current sheet context
        self.current_sheet_df = None
        self.current_start_row_idx = None
        self.column_mappings = {}

        # Track seen variable names across all sheets
        self.seen_vars = set()

    #
    # --- New primitives for multi‐sheet processing ---
    #
    def CreateOutputSheet(self, sheetName):
        """Initialize or clear the single output‐sheet buffer."""
        self.output_sheet_name = sheetName
        self.output_df = pd.DataFrame()

    def ProcessSheet(self, sheetName, startRow):
        """
        Load a sheet by name, apply map.json renames, skip to startRow,
        and prepare to append rows into the output buffer.
        """
        # If we were in another sheet, commit it first
        if self.current_sheet_df is not None:
            self._commit_current_sheet()

        if self.excel is None:
            raise ValueError("No Excel workbook loaded; cannot ProcessSheet")

        # Load the sheet
        df = self.excel.parse(sheetName, dtype=str).fillna('')

        # Apply map.json renames (like the old --map flag)
        for canon, info in self.map.items():
            raw = info.get('fieldname')
            if not info.get('override', False) and raw in df.columns:
                df.rename(columns={raw: canon}, inplace=True)

        self.current_sheet_df = df
        self.current_start_row_idx = int(startRow) - 2
        self.column_mappings = {}

    def MapColumn(self, fromName, toName):
        """
        Record and enact a mapping of a raw header into a canonical header
        in the current sheet.
        """
        if self.current_sheet_df is None:
            raise ValueError("MapColumn outside of ProcessSheet context")
        if fromName in self.current_sheet_df.columns:
            self.current_sheet_df.rename(columns={fromName: toName}, inplace=True)
        self.column_mappings[fromName] = toName

    def DeleteRowsIfEmpty(self, columnList):
        """
        Drop any row in the current sheet where ANY of the listed canonical
        columns is blank or whitespace.
        """
        if self.current_sheet_df is None:
            raise ValueError("DeleteRowsIfEmpty outside of ProcessSheet context")
        # Ensure columns exist
        for col in columnList:
            if col not in self.current_sheet_df.columns:
                self.current_sheet_df[col] = ''

        # Build mask: keep rows where ALL listed columns are non‐empty
        mask = ~self.current_sheet_df[columnList] \
            .applymap(lambda x: str(x).strip() == '').any(axis=1)

        self.current_sheet_df = self.current_sheet_df[mask].reset_index(drop=True)

    #
    # --- Adapted existing primitives to work on current_sheet_df ---
    #
    def EnsureColumn(self, header):
        if self.current_sheet_df is None:
            raise ValueError("EnsureColumn outside of ProcessSheet context")
        if header not in self.current_sheet_df.columns:
            self.current_sheet_df[header] = ''

    def SetCell(self, row, columnName, value):
        """
        Generic setter: set a constant string in the given row and column.
        Row is the 1-based Excel row number, so idx = row-2.
        """
        if self.current_sheet_df is None:
            raise ValueError("SetCell outside of ProcessSheet context")
        idx = int(row) - 2
        self.EnsureColumn(columnName)
        if 0 <= idx < len(self.current_sheet_df):
            self.current_sheet_df.at[idx, columnName] = value

    def SetFormName(self, row, formname):
        return self.SetCell(row, 'Form Name', formname)

    def SetVariableName(self, row, newname):
        if self.current_sheet_df is None:
            raise ValueError("SetVariableName outside of ProcessSheet context")
        idx = int(row) - 2
        if 0 <= idx < len(self.current_sheet_df):
            # ensure uniqueness across all sheets
            base, suffix = newname, 2
            candidate = newname
            while candidate in self.seen_vars:
                candidate = f"{base}_{suffix}"
                suffix += 1
            self.EnsureColumn('Variable / Field Name')
            self.current_sheet_df.at[idx, 'Variable / Field Name'] = candidate
            self.seen_vars.add(candidate)

    def SetFieldType(self, row, ftype):
        return self.SetCell(row, 'Field Type', ftype)

    def ClearCell(self, row, col):
        return self.SetCell(row, col, '')

    def SetChoices(self, row, choices):
        if self.current_sheet_df is None:
            raise ValueError("SetChoices outside of ProcessSheet context")
        idx = int(row) - 2
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        if 0 <= idx < len(self.current_sheet_df):
            self.current_sheet_df.at[idx, col] = ' | '.join(f"{c},{l}" for c, l in choices)

    def SetSlider(self, row, mn, mn_lbl, mx, mx_lbl):
        if self.current_sheet_df is None:
            raise ValueError("SetSlider outside of ProcessSheet context")
        idx = int(row) - 2
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        if 0 <= idx < len(self.current_sheet_df):
            self.current_sheet_df.at[idx, col] = f"{mn},{mn_lbl} | {mx},{mx_lbl}"

    def SetFormula(self, row, formula):
        if self.current_sheet_df is None:
            raise ValueError("SetFormula outside of ProcessSheet context")
        idx = int(row) - 2
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        if 0 <= idx < len(self.current_sheet_df):
            self.current_sheet_df.at[idx, col] = formula

    def SetFormat(self, row, fmt):
        if self.current_sheet_df is None:
            raise ValueError("SetFormat outside of ProcessSheet context")
        idx = int(row) - 2
        col = 'Text Validation Type OR Show Slider Number'
        self.EnsureColumn(col)
        if 0 <= idx < len(self.current_sheet_df):
            self.current_sheet_df.at[idx, col] = fmt

    def SetValidation(self, row, vtype, vmin, vmax):
        if self.current_sheet_df is None:
            raise ValueError("SetValidation outside of ProcessSheet context")
        idx = int(row) - 2
        c1 = 'Text Validation Type OR Show Slider Number'
        c2 = 'Text Validation Min'
        c3 = 'Text Validation Max'
        for c in (c1, c2, c3):
            self.EnsureColumn(c)
        if 0 <= idx < len(self.current_sheet_df):
            self.current_sheet_df.at[idx, c1] = vtype
            self.current_sheet_df.at[idx, c2] = vmin
            self.current_sheet_df.at[idx, c3] = vmax

    #
    # --- Internal: commit current sheet to the output buffer ---
    #
    def _commit_current_sheet(self):
        if self.current_sheet_df is None:
            return
        if self.output_df is None:
            self.output_df = self.current_sheet_df.copy()
        else:
            self.output_df = pd.concat(
                [self.output_df, self.current_sheet_df],
                ignore_index=True
            )
        # reset context
        self.current_sheet_df = None
        self.column_mappings = {}
        self.current_start_row_idx = None


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
            args.append(a.id)
        else:
            args.append(ast.literal_eval(a))
    return name, args


def main():
    args = parse_args()
    src = Path(args.dict)
    # Load workbook if XLS/XLSX, else we won’t support multi‐sheet
    if src.suffix.lower() in ('.xls', '.xlsx'):
        excel = pd.ExcelFile(src)
    else:
        print("Error: multi‐sheet processing requires an XLS/XLSX input", file=sys.stderr)
        sys.exit(1)

    # Load map.json
    mapping = json.loads(Path(args.map).read_text(encoding='utf-8'))

    executor = DSLExecutor(excel, mapping)

    # Read and execute each DSL line
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
        try:
             fn(*params)
        except ValueError as e:
             print(f"Error: {e}", file=sys.stderr)
             sys.exit(1)

    # Commit the final sheet, then write out the buffer
    executor._commit_current_sheet()

    out = Path(args.output)
    suffix = out.suffix.lower()
    if suffix in ('.xls', '.xlsx'):
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            sheet = executor.output_sheet_name or 'Output'
            executor.output_df.to_excel(writer, sheet_name=sheet, index=False)
    elif suffix == '.csv':
        executor.output_df.to_csv(out, index=False)
    else:
        raise ValueError(f"Unsupported output format: {suffix}")

    print(f"Wrote output sheet '{executor.output_sheet_name}' to {out}")


if __name__ == '__main__':
    main()
