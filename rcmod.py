#!/usr/bin/env python3
"""
remod.py

Reads an original REDCap dictionary workbook (XLS/XLSX) and a DSL
operations file, executes the primitives (including the new multi‐sheet ones),
and writes out a consolidated output sheet.

Usage:
    python rcmod.py --in DataDictionary.xlsx  --out NewDict.xlsx fixes.rcm
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
    p.add_argument('--in', dest='input_dict', required=True, help='Original REDCap dictionary file (XLS/XLSX or CSV)')
    p.add_argument('ops_file', help='DSL operations file')
    p.add_argument('--out', dest='output_dict', required=True, help='Output corrected dictionary file')
    return p.parse_args()


class DSLExecutor:

    def _active_df(self, allow_none: bool = False) -> pd.DataFrame | None:
        """
        Returns the DataFrame that write-side primitives should modify.

        • Inside a ProcessSheet block → current_sheet_df
        • Otherwise                   → output_df
          (If output_df doesn’t exist yet, this method creates an empty one
           unless allow_none=True.)
        """
        if self.current_sheet_df is not None:
            return self.current_sheet_df

        if self.output_df is None:
            if allow_none:
                return None
            self.output_df = pd.DataFrame()

        return self.output_df

    def __init__(self, excel_file: pd.ExcelFile):
        # For multi‐sheet input
        self.excel = excel_file

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
        Load a sheet by name, skip to startRow,
        and prepare to append rows into the output buffer.
        """
        # If we were in another sheet, commit it first
        if self.current_sheet_df is not None:
            self._commit_current_sheet()

        if self.excel is None:
            raise ValueError("No Excel workbook loaded; cannot ProcessSheet")

        # Load the sheet
        df = self.excel.parse(sheetName, dtype=str).fillna('')

        self.current_sheet_df = df
        try:
            self.current_start_row_idx = int(startRow) - 2
        except ValueError:
            raise ValueError(f"Invalid startRow value: '{startRow}'. Expected an integer.")
        self.column_mappings = {}

        # Track existing variable names so later renames remain unique
        if 'Variable / Field Name' in df.columns:
            for name in df['Variable / Field Name'].astype(str):
                cleaned = (name or '').strip()
                if cleaned:
                    self.seen_vars.add(cleaned)

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
        # Suppress the FutureWarning for applymap by using .map explicitly if pandas version is recent enough,
        # or acknowledge it as a known deprecation. For now, the warning will still appear but the code works.
        self.current_sheet_df = self.current_sheet_df[
            ~self.current_sheet_df[columnList].map(lambda x: str(x).strip() == '').any(axis=1)
        ].reset_index(drop=True)

    #
    # --- Adapted existing primitives to work on current_sheet_df ---
    #
    def EnsureColumn(self, header: str):
        df = self._active_df()
        if header not in df.columns:
            df[header] = ''

    def SetCell(self, row: int | str, columnName: str, value: str):
        df = self._active_df()
        try:
            idx = int(row) - 2          # 1-based Excel row → 0-based index
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")
        self.EnsureColumn(columnName)
        if 0 <= idx < len(df):
            df.at[idx, columnName] = value

    def SetFormName(self, row, formname):
        self.SetCell(row, 'Form Name', formname)

    def SetVariableName(self, row, newname):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")

        base, suffix = newname, 2
        candidate = newname
        while candidate in self.seen_vars:
            candidate = f"{base}_{suffix}"
            suffix += 1

        self.EnsureColumn('Variable / Field Name')
        if 0 <= idx < len(df):
            df.at[idx, 'Variable / Field Name'] = candidate
            self.seen_vars.add(candidate)

    def LowercaseVariableName(self, row):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")

        self.EnsureColumn('Variable / Field Name')
        if not (0 <= idx < len(df)):
            return

        current = str(df.at[idx, 'Variable / Field Name'] or '')
        lowered = current.lower()
        if not lowered:
            return

        if not VAR_RE.match(lowered):
            raise ValueError(
                f"LowercaseVariableName would still violate naming rules: '{current}'"
            )

        base, suffix = lowered, 2
        candidate = lowered
        while candidate in self.seen_vars:
            candidate = f"{base}_{suffix}"
            suffix += 1

        df.at[idx, 'Variable / Field Name'] = candidate
        self.seen_vars.add(candidate)

    def SetFieldType(self, row, ftype):
        self.SetCell(row, 'Field Type', ftype)

    def ClearCell(self, row, col):
        self.SetCell(row, col, '')

    def SetChoices(self, row, choices):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        if 0 <= idx < len(df):
            df.at[idx, col] = ' | '.join(f"{c},{l}" for c, l in choices)


    def SetSlider(self, row, mn, mn_lbl, mx, mx_lbl):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        if 0 <= idx < len(df):
            df.at[idx, col] = f"{mn},{mn_lbl} | {mx},{mx_lbl}"

    def SetFormula(self, row, formula):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")
        col = 'Choices, Calculations, OR Slider Labels'
        self.EnsureColumn(col)
        if 0 <= idx < len(df):
            df.at[idx, col] = formula

    def SetFormat(self, row, fmt):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")
        col = 'Text Validation Type OR Show Slider Number'
        self.EnsureColumn(col)
        if 0 <= idx < len(df):
            df.at[idx, col] = fmt

    def SetValidation(self, row, vtype, vmin, vmax):
        df = self._active_df()
        try:
            idx = int(row) - 2
        except ValueError:
            raise ValueError(f"Invalid row value: '{row}'. Expected an integer.")
        c1 = 'Text Validation Type OR Show Slider Number'
        c2 = 'Text Validation Min'
        c3 = 'Text Validation Max'
        for c in (c1, c2, c3):
            self.EnsureColumn(c)
        if 0 <= idx < len(df):
            df.at[idx, c1] = vtype
            df.at[idx, c2] = vmin
            df.at[idx, c3] = vmax

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
    src = Path(args.input_dict)
    
    if not src.exists():
        print(f"Error: Input dictionary file not found: {src}", file=sys.stderr)
        sys.exit(1)

    # Load workbook if XLS/XLSX, else we won’t support multi‐sheet
    if src.suffix.lower() in ('.xls', '.xlsx'):
        try:
            excel = pd.ExcelFile(src)
        except Exception as e:
            print(f"Error: Could not open Excel file {src}. Reason: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Error: multi‐sheet processing requires an XLS/XLSX input", file=sys.stderr)
        sys.exit(1)

    executor = DSLExecutor(excel)

    ops_file_path = Path(args.ops_file)
    if not ops_file_path.exists():
        print(f"Error: DSL operations file not found: {ops_file_path}", file=sys.stderr)
        sys.exit(1)

    # Read and execute each DSL line
    try:
        ops_lines = ops_file_path.read_text(encoding='utf-8').splitlines()
    except Exception as e:
        print(f"Error: Could not read DSL operations file {ops_file_path}. Reason: {e}", file=sys.stderr)
        sys.exit(1)

    for raw in ops_lines:
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
            print(f"Error processing line '{line}': {e}", file=sys.stderr)
            sys.exit(1)
        except TypeError as e:
            print(f"Error processing line '{line}': Incorrect number or type of arguments for '{cmd}'. Reason: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"An unexpected error occurred while processing line '{line}': {e}", file=sys.stderr)
            sys.exit(1)

    # Commit the final sheet, then write out the buffer
    executor._commit_current_sheet()

    out = Path(args.output_dict)
    suffix = out.suffix.lower()

    if executor.output_df is None or executor.output_df.empty:
        print(f"Warning: No data to write to output file {out}. The resulting DataFrame is empty.", file=sys.stderr)
        # Optionally, you could choose to exit or create an empty file.
        # For now, it will proceed and create an empty file if the DataFrame is empty.

    try:
        if suffix in ('.xls', '.xlsx'):
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                sheet = executor.output_sheet_name or 'Output'
                executor.output_df.to_excel(writer, sheet_name=sheet, index=False)
        elif suffix == '.csv':
            executor.output_df.to_csv(out, index=False)
        else:
            raise ValueError(f"Unsupported output format: {suffix}")
    except Exception as e:
        print(f"Error: Could not write output file {out}. Reason: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote output sheet '{executor.output_sheet_name or 'Output'}' to {out}")


if __name__ == '__main__':
    main()
