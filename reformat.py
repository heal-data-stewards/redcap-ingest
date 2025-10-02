#!/usr/bin/env python3
"""
redcap_dsl_gen.py
─────────────────
Generate a DSL script (in the primitives document) that performs the same
normalisation as redcap_format.py --map … --out … .

Usage
─────
  python redcap_dsl_gen.py <DICT.xlsx/CSV> [--map MAP.json] [--out OUT.rcm]
                          [--elide-unlabeled]

Defaults
────────
  --map  → <DICT path>/<DICT basename>-map.json
  --out  → <DICT path>/<DICT basename>-reformat.rcm

The MAP.json must be the file produced previously via --generate-map.
"""

from __future__ import annotations
import argparse, json, sys, re
from pathlib import Path
from typing import Dict, Any, List, Tuple
import pandas as pd

# ───────────────────────── Canonical REDCap headers ─────────────────────────
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

# ――――――――――――――――― helper: load a sheet & find header row ――――――――――――――――
VAR_RE = re.compile(r"^[a-z][a-z0-9_]{0,25}$")

def find_header_row(df0: pd.DataFrame, header_guess: int = 20) -> int:
    """
    Naïve heuristic: the first row where at least one cell matches the variable-name regex.
    Falls back to row 0.
    """
    max_scan = min(header_guess, len(df0) - 1)
    for i in range(max_scan):
        if any(VAR_RE.match(str(x or "")) for x in df0.iloc[i]):
            return i
    return 0

def load_sheet(path: Path, sheet: str, start_row: int | None) -> Tuple[pd.DataFrame,int]:
    """
    Returns (df, header_row_1based).  start_row from map.json is already 1-based;
    if absent, we auto-detect.
    """
    if path.suffix.lower() in {".xls", ".xlsx"}:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
    else:  # CSV passed with sheet name ""
        raw = pd.read_csv(path, header=None, dtype=str)
    hdr_idx = (start_row-1) if start_row else find_header_row(raw)
    header = raw.iloc[hdr_idx].fillna("").astype(str).tolist()
    data   = raw.iloc[hdr_idx+1:].fillna("")
    data.columns = header
    return data, hdr_idx+1  # convert to 1-based as DSL expects

# ――――――――――――――――――――――― DSL generation ――――――――――――――――――――――――――――
def emit(line: str, out: List[str]) -> None:
    out.append(line)

def ensure_canon_columns(out: List[str]) -> None:
    for col in ALL:
        emit(f'EnsureColumn("{col}")', out)

def generate_dsl(
    dict_path: Path,
    map_json: Path,
    dsl_out: Path,
    elide_unlabeled: bool,
) -> None:
    cfg_all = json.loads(map_json.read_text())

    dsl: List[str] = []
    emit('CreateOutputSheet("REDCap")', dsl)
    ensure_canon_columns(dsl)

    # delete-row rule
    del_cols = ['"Variable / Field Name"']
    if elide_unlabeled:
        del_cols.append('"Field Label"')

    for sheet_name, cfg in cfg_all.items():
        if cfg.get("ignore", False):
            print(f"⏭️  Skipping sheet '{sheet_name}' (ignore=true)")
            continue

        start_row = cfg.get("start_row")          # 1-based or None
        mapping   = cfg.get("mapping", {})        # canon → raw
        immed     = cfg.get("immediate", {})      # canon → value

        # 1) figure out header row if map lacks it, load sheet to know row count
        df, header_1based = load_sheet(dict_path, sheet_name, start_row)
        start_row = header_1based  # now guaranteed
        emit(f'\n# ── {sheet_name} ──', dsl)
        emit(f'ProcessSheet("{sheet_name}", {start_row})', dsl)

        # 2) Map raw→canonical
        for canon, raw in mapping.items():
            emit(f'MapColumn("{raw}", "{canon}")', dsl)

        # 3) Delete blank-variable rows (+ optional unlabeled)
        emit(f'DeleteRowsIfEmpty([{", ".join(del_cols)}])', dsl)

        # 4) Inject immediates row-by-row
        if immed:
            # absolute row numbers in original sheet = start_row + i
            for i, _ in df.iterrows():
                row_num = i + start_row + 1  # pandas index starts at 0
                if "Form Name" in immed:
                    emit(f'SetFormName({row_num}, "{immed["Form Name"]}")', dsl)
                for canon, val in immed.items():
                    if canon == "Form Name":
                        continue
                    emit(f'SetCell({row_num}, "{canon}", "{val}")', dsl)

    # write out
    dsl_out.write_text("\n".join(dsl) + "\n")
    print(f"DSL script with {len(dsl):,} lines → {dsl_out}")

# ――――――――――――――――――――――― CLI ―――――――――――――――――――――――――――――――――――――――――――
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dict_file", help="Original Excel/CSV dictionary")
    ap.add_argument(
        "--map",
        dest="map_file",
        help="map.json produced by --generate-map (defaults to <DICT>-map.json)",
        required=False,
    )
    ap.add_argument(
        "--out",
        dest="out_file",
        help="Path to write the generated DSL (defaults to <DICT>-reformat.rcm)",
        required=False,
    )
    ap.add_argument(
        "--elide-unlabeled",
        action="store_true",
        help="Also delete rows with blank Field Label",
    )
    args = ap.parse_args()

    dict_path = Path(args.dict_file).resolve()
    base = dict_path.stem

    # Compute defaults if not provided
    map_path = Path(args.map_file) if args.map_file else dict_path.with_name(f"{base}-map.json")
    out_path = Path(args.out_file) if args.out_file else dict_path.with_name(f"{base}-reformat.rcm")

    generate_dsl(
        dict_path=dict_path,
        map_json=map_path,
        dsl_out=out_path,
        elide_unlabeled=args.elide_unlabeled,
    )

if __name__ == "__main__":
    main()
