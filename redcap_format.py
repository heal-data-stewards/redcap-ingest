#!/usr/bin/env python3
"""
redcap_format.py

1. --generate-map  → scans every sheet and writes a JSON per-sheet map:
     {
       "Sheet1": {
         "mapping":        { "<Canon>": "<rawCol>", … },
         "missing_required": [ "<Canon1>", … ],
         // optional: user can add
         "ignore": true,               # skip this sheet on --map
         "immediate": {                # fill these columns with constants
           "Form Name": "MyForm",
           …
         }
       },
       …
     }

2. --map FILE      → loads that JSON, applies it to each sheet (unless `"ignore": true`),
   --output OUT    → writes a single-sheet Excel combining all sheets,
                    with exactly the 16 canonical columns in order,
                    filling missing optionals with blanks,
                    filling any `"immediate"` constants,
                    and—if still no Form Name—using the sheet name.
"""

from __future__ import annotations
import argparse, json, sys, re
from pathlib import Path
from typing import Dict, Any, List, Set
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

FIELD_TYPES = {
    "text", "notes", "radio", "checkbox", "dropdown", "calc", "file",
    "yesno", "truefalse", "slider", "descriptive", "date", "datetime",
}

VAR_RE = re.compile(r"^[a-z][a-z0-9_]{0,25}$")
CHOICE_COL = "Choices, Calculations, OR Slider Labels"

SYNONYM: Dict[str, str] = {
    "variable": "Variable / Field Name",
    "var":      "Variable / Field Name",
    "label":    "Field Label",
    "type":     "Field Type",
    "notes":    "Field Note",
    "note":     "Field Note",
    "branchinglogic": "Branching Logic",
    "showfieldonlyif": "Branching Logic",
    "sectionheader": "Section Header",
    "identifier": "Identifier?",
    "required":   "Required Field?",
    "align":      "Custom Alignment",
    "questionnumber": "Question Number (surveys only)",
    "annotation":      "Field Annotation",
    "choices":         CHOICE_COL,
    "permissiblevalues": CHOICE_COL,
    "validation":      "Text Validation Type OR Show Slider Number",
}

def normalise(name: str) -> str:
    return re.sub(r"\W+", "", name).lower()

# ──────────────────────────── Scoring functions ─────────────────────────────
def score_var(s: pd.Series) -> float:
    non = s[s != ""]
    if non.empty: return 0.0
    return 0.5 * non.str.match(VAR_RE).mean() + 0.5 * (non.nunique() / len(non))

def score_form(s: pd.Series) -> float:
    non = s[s != ""]
    if non.empty: return 0.0
    return 0.7 * non.str.match(VAR_RE).mean() + 0.3 * (1 - non.nunique() / len(non))

def score_type(s: pd.Series) -> float:
    non = s[s != ""]
    if non.empty: return 0.0
    return non.str.lower().isin(FIELD_TYPES).mean()

def score_label(colname: str, s: pd.Series) -> float:
    non = s[s != ""]
    if non.empty: return 0.0
    base = non.str.contains(r"\s").mean()
    return base + (0.25 if "label" in colname.lower() else 0)

# Optional‐column heuristics:
_VALIDATION_TYPES: Set[str] = {
    "integer", "number", "date_mdy", "date_dmy", "time",
    "datetime_mdy", "datetime_dmy", "email", "phone"
}
_YN = {"y", "n", "yes", "no", "true", "false"}

def score_section_header(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.contains(r"\s").mean() or 0.0

def score_choices(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.contains(r"\|").mean() or 0.0

def score_field_note(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.len().gt(20).mean() or 0.0

def score_text_validation_type(s: pd.Series) -> float:
    non = s[s != ""].str.lower()
    return non.empty and non.isin(_VALIDATION_TYPES).mean() or 0.0

def score_text_validation_min(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.match(r"^-?\d+(\.\d+)?$").mean() or 0.0

def score_text_validation_max(s: pd.Series) -> float:
    return score_text_validation_min(s)

def score_identifier(s: pd.Series) -> float:
    non = s[s != ""].str.lower()
    return non.empty and non.isin(_YN).mean() or 0.0

def score_branching_logic(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.contains(r"\[.*\]").mean() or 0.0

def score_required_field(s: pd.Series) -> float:
    return score_identifier(s)

def score_custom_alignment(s: pd.Series) -> float:
    non = s[s != ""].str.upper()
    return non.empty and non.isin({"L","C","R","LEFT","CENTER","RIGHT"}).mean() or 0.0

def score_question_number(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.match(r"^\d+(\.\d+)?$").mean() or 0.0

def score_field_annotation(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.startswith("@").mean() or 0.0

# Build the DETECT map for all 16 headers
DETECT: Dict[str, Any] = {
    "Variable / Field Name":             score_var,
    "Form Name":                         score_form,
    "Field Type":                        score_type,
    "Field Label":                       lambda s: score_label(s.name, s),
    "Section Header":                    score_section_header,
    CHOICE_COL:                          score_choices,
    "Field Note":                        score_field_note,
    "Text Validation Type OR Show Slider Number": score_text_validation_type,
    "Text Validation Min":               score_text_validation_min,
    "Text Validation Max":               score_text_validation_max,
    "Identifier?":                       score_identifier,
    "Branching Logic":                   score_branching_logic,
    "Required Field?":                   score_required_field,
    "Custom Alignment":                  score_custom_alignment,
    "Question Number (surveys only)":    score_question_number,
    "Field Annotation":                  score_field_annotation,
}

# ───────────────────────── resolve_headers ─────────────────────────
def resolve_headers(df: pd.DataFrame, user_map: Dict[str, str]) -> tuple[pd.DataFrame, List[str], Dict[str, str]]:
    raw_cols = list(df.columns)
    col2canon: Dict[str, str] = {}
    canon_norm = {normalise(c): c for c in ALL}

    # 1) exact matches
    for col in raw_cols:
        n = normalise(col)
        if n in canon_norm and canon_norm[n] not in col2canon.values():
            col2canon[col] = canon_norm[n]

    # 2) synonyms
    for col in raw_cols:
        if col in col2canon: continue
        n = normalise(col)
        for syn, canon in SYNONYM.items():
            if syn in n and canon not in col2canon.values():
                col2canon[col] = canon
                break

    # 3) user overrides
    for raw, canon in user_map.items():
        col2canon[raw] = canon

    # apply the current mapping
    df = df.rename(columns=col2canon)

    # 4) heuristics on every remaining header
    still_need = [c for c in ALL if c not in df.columns]
    unmapped   = [c for c in df.columns if c not in ALL]
    mapping: Dict[str, str] = {}

    for canon in still_need:
        if canon not in DETECT:
            continue
        best, best_score = None, 0.0
        for col in unmapped:
            # grab the column; if duplicates, pick the first
            col_data = df[col]
            if isinstance(col_data, pd.DataFrame):
                col_data = col_data.iloc[:, 0]
            # score
            score = DETECT[canon](col_data)
            if score > best_score:
                best, best_score = col, score
        if best_score >= 0.8:
            mapping[best] = canon
            unmapped.remove(best)

    if mapping:
        df = df.rename(columns=mapping)
        col2canon |= mapping

    # anything not in col2canon is unknown
    unknown = [c for c in raw_cols if c not in col2canon]
    return df, unknown, col2canon


def find_header_row(df0: pd.DataFrame, user_map: Dict[str,str], max_scan: int = 20) -> int:
    """
    Try rows 0..max_scan-1 as potential header. For each:
      1) use that row as df.columns,
      2) call resolve_headers() on the sub-DataFrame below,
      3) count how many canonical headers we actually mapped.
    Return the 0-based index with highest mapped count (ties → earliest).
    """
    best_idx = 0
    best_mapped = -1

    # We need at least one row of data below the header
    limit = min(max_scan, len(df0) - 1)
    for i in range(limit):
        # extract header names
        header = df0.iloc[i].fillna("").astype(str).tolist()
        sub = df0.iloc[i+1 :].copy()
        sub.columns = header
        sub = sub.fillna("")

        # run your existing mapping logic
        _, _, col2canon = resolve_headers(sub, user_map)
        mapped = len(col2canon)  # number of raw→canon mappings found

        if mapped > best_mapped:
            best_mapped = mapped
            best_idx = i

    return best_idx


def load_all_sheets(path: Path, user_map: Dict[str,str]) -> dict[str, pd.DataFrame]:
    """
    Load every sheet from an Excel, using find_header_row() to detect the real header.
    Returns sheet_name → cleaned DataFrame.
    """
    if path.suffix.lower() in {".xls", ".xlsx"}:
        raw_sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
        cleaned: Dict[str, pd.DataFrame] = {}

        for name, df0 in raw_sheets.items():
            header_idx = find_header_row(df0, user_map)
            header  = df0.iloc[header_idx].fillna("").astype(str).tolist()
            data    = df0.iloc[header_idx + 1 :].copy()
            data.columns = header
            cleaned[name] = data.fillna("")

        return cleaned

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str).fillna("")
        return {"": df}

    raise ValueError(f"Unsupported file type: {path.suffix}")




def generate_map( path: Path, out: Path, user_map: Dict[str, str], default_immediate: Dict[str, str]):
    """
    Builds a per-sheet map that includes:
      - mapping:          raw→canonical columns
      - missing_required: any REQ headers not auto-detected (minus defaults & Form Name)
      - start_row:        detected header row (1-based)
      - immediate:        sheet-level constants, including Form Name and defaults
    """
    all_sheets = load_all_sheets(path,user_map)
    mapping_out: Dict[str, Any] = {}

    for sheet_name, df in all_sheets.items():
        # 1) detect header row for start_row
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=str)
        hdr0 = find_header_row(raw,user_map)
        start_row = hdr0 + 1

        # 2) auto-detect columns
        _, _, col2canon = resolve_headers(df, user_map)
        canon2raw = {canon: raw for raw, canon in col2canon.items()}

        # 3) compute missing_required (REQ not mapped)
        missing_req = [c for c in REQ if c not in canon2raw]

        # 4) build base sheet config
        sheet_cfg: Dict[str, Any] = {
            "mapping":          canon2raw,
            "missing_required": [],
            "start_row":        start_row,
        }

        # 5) always inject Form Name if missing
        immediate: Dict[str, str] = {}
        if "Form Name" not in canon2raw:
            immediate["Form Name"] = sheet_name
            # remove it from missing_req if present
            if "Form Name" in missing_req:
                missing_req.remove("Form Name")

        # 6) apply any other global defaults
        for canon, val in default_immediate.items():
            if canon != "Form Name" and canon not in canon2raw:
                immediate[canon] = val
            # also drop from missing_req
            if canon in missing_req:
                missing_req.remove(canon)

        # 7) record what’s still truly missing
        sheet_cfg["missing_required"] = missing_req

        # 8) attach immediates if any
        if immediate:
            sheet_cfg["immediate"] = immediate

        mapping_out[sheet_name] = sheet_cfg

    # 9) write JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapping_out, indent=2))
    print(f"Generated map for {len(mapping_out)} sheets → {out}")

def apply_map(
    source_excel: Path,
    map_json: Path,
    output_excel: Path,
    elide_unlabeled: bool = False,
):
    """
    Applies the JSON map to source_excel, concatenates all sheets,
    skips blank Variable rows, and if elide_unlabeled is True, also
    skips rows where Field Label is blank.
    """
    mapping_cfg = json.loads(map_json.read_text())
    xls = pd.ExcelFile(source_excel)
    result_sheets = []

    for sheet_name in xls.sheet_names:
        cfg = mapping_cfg.get(sheet_name, {})
        if not cfg or cfg.get("ignore", False):
            print(f"⏭️  Skipping sheet '{sheet_name}'")
            continue

        start_row  = cfg.get("start_row", 1)
        raw_map    = cfg.get("mapping", {})
        immediate  = cfg.get("immediate", {})

        # 1) Read with no header
        df0 = pd.read_excel(source_excel, sheet_name=sheet_name, header=None, dtype=str)

        # 2) Extract header & data
        hdr  = df0.iloc[start_row-1].fillna("").astype(str).tolist()
        data = df0.iloc[start_row:].copy()
        data.columns = hdr
        df2 = data.fillna("")

        # 3) Rename raw→canonical
        rename_map = { raw: canon for canon, raw in raw_map.items() }
        df2 = df2.rename(columns=rename_map)

        # 4) Inject immediates
        for canon, val in immediate.items():
            df2[canon] = val

        # 5) Ensure all 16 REDCap columns exist
        for col in ALL:
            if col not in df2.columns:
                df2[col] = ""

        # 6) Drop rows where Variable is blank
        mask = df2["Variable / Field Name"].astype(str).str.strip().ne("")
        #    and, if requested, drop rows where Field Label is blank
        if elide_unlabeled:
            mask &= df2["Field Label"].astype(str).str.strip().ne("")

        df2 = df2.loc[mask]

        # 7) Reorder to standard layout
        df2 = df2[ALL]

        result_sheets.append(df2)

    if not result_sheets:
        sys.exit("ERROR: No sheets to write (all were ignored or empty).")

    # 8) Concatenate and write
    final_df = pd.concat(result_sheets, ignore_index=True)
    output_excel.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
        final_df.to_excel(writer, index=False, sheet_name="REDCap")
    print(f"Wrote normalized REDCap file with {len(result_sheets)} sheets → {output_excel}")

# ─────────────────────────────── main ────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("dict_file", help="Excel/CSV to scan or normalize")
    p.add_argument("--generate-map",
                   help="Path to write JSON map of raw→canon per sheet")
    p.add_argument("--map",
                   dest="map_file",
                   help="Path to JSON map (from --generate-map) to apply")
    p.add_argument("--output",
                   help="Path for generated Excel when using --map")
    p.add_argument( "--default-immediate", action="append", metavar="CANON=VALUE",
                   help="Default immediate value for a canonical column if not detected; repeatable")
    p.add_argument("--elide-unlabeled", action="store_true",
                   help="When mapping, also skip rows with a blank Field Label",)
    args = p.parse_args()

    # build the default-immediate dictionary
    default_immediate: Dict[str, str] = {}
    if args.default_immediate:
        for tok in args.default_immediate:
            if "=" not in tok:
                sys.exit("ERROR: --default-immediate must be CANON=VALUE")
            canon, val = tok.split("=", 1)
            if canon not in ALL:
                sys.exit(f"ERROR: unknown canonical column '{canon}'")
            default_immediate[canon] = val

    if args.generate_map:
        generate_map(
            Path(args.dict_file),
            Path(args.generate_map),
            user_map={},
            default_immediate=default_immediate
        )
        sys.exit(0)

    if args.map_file:
        if not args.output:
            sys.exit("ERROR: --output is required when using --map")
        apply_map(
            source_excel=Path(args.dict_file),
            map_json=Path(args.map_file),
            output_excel=Path(args.output),
            elide_unlabeled=args.elide_unlabeled,
        )
        sys.exit(0)

    p.print_help()
    sys.exit(1)

if __name__ == "__main__":
    main()
