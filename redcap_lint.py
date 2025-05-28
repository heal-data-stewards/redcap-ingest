#!/usr/bin/env python3
"""
redcap_lint.py – v0.14
~~~~~~~~~~~~~~~~~~~~~
Maps every input column to one of the 16 canonical REDCap headers if possible,
then lints rows.  Unmapped columns are captured but only the summary is printed
to stdout; the full per-line report goes to the JSON file specified by --report,
now including the raw source values for key fields.

Optionally exports the combined column mapping as JSON via --export-map,
but only after required fields are satisfied.  Exported map has canonical
labels as keys and objects {"fieldname": <raw>, "override": <bool>} as values.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Union, Any

import pandas as pd

# ───────────────────────── Canonical REDCap headers
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

# ───────────────────────── synonym table
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
    "choices":         "Choices, Calculations, OR Slider Labels",
    "permissiblevalues": "Choices, Calculations, OR Slider Labels",
    "validation":      "Text Validation Type OR Show Slider Number",
}

def normalise(name: str) -> str:
    return re.sub(r"\W+", "", name).lower()

def load_dict(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str).fillna("")
    if path.suffix.lower() in {".xls", ".xlsx"}:
        return pd.read_excel(path, dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {path.suffix}")

def load_mapping(path: Path | None) -> Dict[str, Any]:
    if not path:
        return {}
    return json.loads(path.read_text())

def score_var(s: pd.Series) -> float:
    non = s[s != ""]
    return 0 if non.empty else 0.5 * non.str.match(VAR_RE).mean() + 0.5 * (non.nunique() / len(non))

def score_form(s: pd.Series) -> float:
    non = s[s != ""]
    return 0 if non.empty else 0.7 * non.str.match(VAR_RE).mean() + 0.3 * (1 - non.nunique() / len(non))

def score_type(s: pd.Series) -> float:
    non = s[s != ""]
    return 0 if non.empty else non.str.lower().isin(FIELD_TYPES).mean()

def score_label(name: str, s: pd.Series) -> float:
    non = s[s != ""]
    base = 0 if non.empty else non.str.contains(r"\s").mean()
    return base + (0.25 if "label" in name.lower() else 0)

DETECT: Dict[str, Any] = {
    "Variable / Field Name": score_var,
    "Form Name":             score_form,
    "Field Type":            score_type,
    "Field Label":           score_label,
}

def resolve_headers(df: pd.DataFrame, user_map: Dict[str, str]) -> tuple[pd.DataFrame, List[str], Dict[str, str]]:
    raw_cols = list(df.columns)
    col2canon: Dict[str, str] = {}
    canon_norm = {normalise(c): c for c in ALL}

    # exact matches
    for col in raw_cols:
        n = normalise(col)
        if n in canon_norm and canon_norm[n] not in col2canon.values():
            col2canon[col] = canon_norm[n]
    # synonyms
    for col in raw_cols:
        if col in col2canon:
            continue
        n = normalise(col)
        for syn, canon in SYNONYM.items():
            if syn in n and canon not in col2canon.values():
                col2canon[col] = canon
                break
    # user overrides (raw->canon)
    for raw, canon in user_map.items():
        col2canon[raw] = canon

    df = df.rename(columns=col2canon)

    # heuristics
    still_need = [c for c in ALL if c not in df.columns]
    unmapped = [c for c in df.columns if c not in ALL]
    mapping: Dict[str, str] = {}
    if still_need:
        for canon in still_need:
            best, best_score = None, 0.0
            for col in unmapped:
                score = DETECT[canon](df[col]) if canon != "Field Label" else score_label(col, df[col])
                if score > best_score:
                    best, best_score = col, score
            if best_score >= 0.8:
                mapping[best] = canon
                unmapped.remove(best)
        if mapping:
            df = df.rename(columns=mapping)
            col2canon |= mapping

    unknown = [c for c in raw_cols if c not in col2canon]
    return df, unknown, col2canon

def classify_row(row: pd.Series, seen: set[str]) -> tuple[str, List[str]]:
    if (row == "").all():
        return "IGNORE", ["blank line"]
    if str(row.iloc[0]).lstrip().startswith("#"):
        return "IGNORE", ["comment"]

    reasons: List[str] = []
    var = row.get("Variable / Field Name", "").strip()
    if not VAR_RE.match(var):
        reasons.append("invalid variable name")
    elif var in seen:
        reasons.append("duplicate variable name")
    else:
        seen.add(var)

    ftype = row.get("Field Type", "").strip().lower()
    if ftype and ftype not in FIELD_TYPES:
        reasons.append(f"unknown field type '{ftype}'")
    if ftype in {"radio", "checkbox", "dropdown"} and not row.get(CHOICE_COL, "").strip():
        reasons.append("missing choices for multi-choice field")

    return ("ACCEPT" if not reasons else "VIOLATE"), reasons

def lint_dataframe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for i, row in df.iterrows():
        cls, why = classify_row(row, seen)
        valid = cls == "ACCEPT"
        error = None if valid else "; ".join(why)
        # include raw source values for key columns
        records.append({
            "line": i + 2,
            "classification": {"valid": valid, "error": error},
            "Variable / Field Name": row.get("Variable / Field Name", ""),
            "Form Name": row.get("Form Name", ""),
            "Field Type": row.get("Field Type", ""),
            "Field Label": row.get("Field Label", ""),
            CHOICE_COL: row.get(CHOICE_COL, "")
        })
    return records

def print_summary(records: List[Dict[str, Any]]) -> None:
    cnt = {"ACCEPT": 0, "VIOLATE": 0}
    for rec in records:
        if rec["classification"]["valid"]:
            cnt["ACCEPT"] += 1
        else:
            cnt["VIOLATE"] += 1
    print("\nLint Summary\n============")
    print(f"ACCEPT  : {cnt['ACCEPT']}")
    print(f"VIOLATE : {cnt['VIOLATE']}")
    print("============\n")

def main():
    parser = argparse.ArgumentParser(description="Lint a REDCap data dictionary.")
    parser.add_argument('dict_file', help='Path to REDCap data dictionary')
    parser.add_argument('--map', dest='map_file',
                        help='Optional mapping JSON', default=None)
    parser.add_argument('--report', dest='report_file',
                        help='Output JSON report path', default=None)
    parser.add_argument('--form-name', dest='form_name',
                        help='Value to set for Form Name (override)', default=None)
    parser.add_argument('--export-map', dest='export_map',
                        help='Write combined column mapping to JSON file', default=None)
    args = parser.parse_args()

    dict_path = Path(args.dict_file)
    map_path = Path(args.map_file) if args.map_file else None
    report_path = Path(args.report_file) if args.report_file else None
    form_name = args.form_name
    export_map = Path(args.export_map) if args.export_map else None

    if not dict_path.is_file():
        sys.exit(f"ERROR: dictionary file not found: {dict_path}")
    if map_path and not map_path.is_file():
        sys.exit(f"ERROR: mapping file not found: {map_path}")

    raw_map = load_mapping(map_path)
    user_map: Dict[str, str] = {}
    overrides: Dict[str, Dict[str, Union[str, bool]]] = {}
    for key, val in raw_map.items():
        if isinstance(val, dict) and "fieldname" in val and "override" in val:
            overrides[key] = val
            if not val["override"]:
                user_map[val["fieldname"]] = key
        else:
            user_map[key] = val

    try:
        df, unknown_cols, col2canon = resolve_headers(load_dict(dict_path), user_map)
    except Exception as exc:
        sys.exit(f"ERROR: {exc}")

    if "Form Name" in overrides and overrides["Form Name"]["override"]:
        df["Form Name"] = overrides["Form Name"]["fieldname"]
    elif form_name is not None:
        df["Form Name"] = form_name
    elif "Form Name" not in df.columns:
        sys.exit("ERROR: Missing required column 'Form Name' (or specify --form-name)")

    missing = [c for c in REQ if c not in df.columns]
    if missing:
        sys.exit(f"ERROR: Missing required columns: {', '.join(missing)}")

    if export_map:
        export_map.parent.mkdir(parents=True, exist_ok=True)
        inverted = {canon: raw for raw, canon in col2canon.items()}
        mapping_objs: Dict[str, Dict[str, Union[str, bool]]] = {}
        for canon in ALL:
            if canon == "Form Name" and canon in overrides and overrides[canon]["override"]:
                mapping_objs[canon] = {
                    "fieldname": overrides[canon]["fieldname"],
                    "override": True
                }
            elif canon in inverted:
                mapping_objs[canon] = {
                    "fieldname": inverted[canon],
                    "override": False
                }
        text = json.dumps(mapping_objs, indent=2).replace("\n", "\r\n") + "\r\n"
        with open(export_map, "w", newline="") as f:
            f.write(text)
        print(f"Exported column mapping to {export_map}")

    records = lint_dataframe(df)
    print_summary(records)

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(records, f, indent=2)
        print(f"Report written to {report_path}")

    if any(not rec["classification"]["valid"] for rec in records):
        sys.exit(2)

if __name__ == '__main__':
    main()
