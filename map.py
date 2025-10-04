#!/usr/bin/env python3
"""
map.py

Generate a JSON map that captures how raw REDCap-like columns should map to
canonical REDCap headers. The script mirrors the heuristics previously baked
into `redcap_format.py --generate-map` so downstream tools can continue to rely
on the same JSON structure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

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
    "text",
    "notes",
    "radio",
    "checkbox",
    "dropdown",
    "calc",
    "file",
    "yesno",
    "truefalse",
    "slider",
    "descriptive",
    "date",
    "datetime",
}

VAR_RE = re.compile(r"^[a-z][a-z0-9_]{0,25}$")
CHOICE_COL = "Choices, Calculations, OR Slider Labels"

SYNONYM: Dict[str, str] = {
    "variable": "Variable / Field Name",
    "var": "Variable / Field Name",
    "fieldname": "Variable / Field Name",
    "fieldid": "Variable / Field Name",
    "label": "Field Label",
    "fieldlabel": "Field Label",
    "description": "Field Label",
    "fielddescription": "Field Label",
    "type": "Field Type",
    "datatype": "Field Type",
    "notes": "Field Note",
    "note": "Field Note",
    "branchinglogic": "Branching Logic",
    "showfieldonlyif": "Branching Logic",
    "sectionheader": "Section Header",
    "identifier": "Identifier?",
    "required": "Required Field?",
    "align": "Custom Alignment",
    "questionnumber": "Question Number (surveys only)",
    "annotation": "Field Annotation",
    "choices": CHOICE_COL,
    "permissiblevalues": CHOICE_COL,
    "validvalues": CHOICE_COL,
    "validation": "Text Validation Type OR Show Slider Number",
}


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


# ──────────────────────────── Scoring functions ─────────────────────────────
def score_var(s: pd.Series) -> float:
    non = s[s != ""]
    if not non.empty:
        return 0.0
    return 0.5 * non.str.match(VAR_RE).mean() + 0.5 * (non.nunique() / len(non))


def score_form(s: pd.Series) -> float:
    non = s[s != ""]
    if not non.empty:
        return 0.0
    return 0.7 * non.str.match(VAR_RE).mean() + 0.3 * (1 - non.nunique() / len(non))


def score_type(s: pd.Series) -> float:
    non = s[s != ""]
    if not non.empty:
        return 0.0
    return non.str.lower().isin(FIELD_TYPES).mean()


def score_label(colname: str, s: pd.Series) -> float:
    non = s[s != ""]
    if not non.empty:
        return 0.0
    base = non.str.contains(r"\s").mean()
    return base + (0.25 if "label" in colname.lower() else 0)


_VALIDATION_TYPES: Set[str] = {
    "integer",
    "number",
    "date_mdy",
    "date_dmy",
    "time",
    "datetime_mdy",
    "datetime_dmy",
    "email",
    "phone",
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
    return non.empty and non.isin({"L", "C", "R", "LEFT", "CENTER", "RIGHT"}).mean() or 0.0


def score_question_number(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.match(r"^\d+(\.\d+)?$").mean() or 0.0


def score_field_annotation(s: pd.Series) -> float:
    non = s[s != ""]
    return non.empty and non.str.startswith("@").mean() or 0.0


DETECT: Dict[str, Any] = {
    "Variable / Field Name": score_var,
    "Form Name": score_form,
    "Field Type": score_type,
    "Field Label": lambda s: score_label(s.name, s),
    "Section Header": score_section_header,
    CHOICE_COL: score_choices,
    "Field Note": score_field_note,
    "Text Validation Type OR Show Slider Number": score_text_validation_type,
    "Text Validation Min": score_text_validation_min,
    "Text Validation Max": score_text_validation_max,
    "Identifier?": score_identifier,
    "Branching Logic": score_branching_logic,
    "Required Field?": score_required_field,
    "Custom Alignment": score_custom_alignment,
    "Question Number (surveys only)": score_question_number,
    "Field Annotation": score_field_annotation,
}


def resolve_headers(df: pd.DataFrame, user_map: Dict[str, str]) -> tuple[pd.DataFrame, List[str], Dict[str, str]]:
    raw_cols = list(df.columns)
    col2canon: Dict[str, str] = {}
    canon_norm = {normalise(c): c for c in ALL}

    for col in raw_cols:
        n = normalise(col)
        if n in canon_norm and canon_norm[n] not in col2canon.values():
            col2canon[col] = canon_norm[n]

    for col in raw_cols:
        if col in col2canon:
            continue
        n = normalise(col)
        for syn, canon in SYNONYM.items():
            if syn in n and canon not in col2canon.values():
                col2canon[col] = canon
                break

    for raw, canon in user_map.items():
        col2canon[raw] = canon

    df = df.rename(columns=col2canon)

    still_need = [c for c in ALL if c not in df.columns]
    unmapped = [c for c in df.columns if c not in ALL]
    mapping: Dict[str, str] = {}

    for canon in still_need:
        if canon not in DETECT:
            continue
        best, best_score = None, 0.0
        for col in unmapped:
            col_data = df[col]
            if isinstance(col_data, pd.DataFrame):
                col_data = col_data.iloc[:, 0]
            score = DETECT[canon](col_data)
            if score > best_score:
                best, best_score = col, score
        if best_score >= 0.8 and best is not None:
            mapping[best] = canon
            unmapped.remove(best)

    if mapping:
        df = df.rename(columns=mapping)
        col2canon |= mapping

    unknown = [c for c in raw_cols if c not in col2canon]
    return df, unknown, col2canon


def find_header_row(df0: pd.DataFrame, user_map: Dict[str, str], max_scan: int = 20) -> int:
    best_idx = 0
    best_mapped = -1

    limit = min(max_scan, len(df0) - 1)
    for i in range(limit):
        header = df0.iloc[i].fillna("").astype(str).tolist()
        sub = df0.iloc[i + 1 :].copy()
        sub.columns = header
        sub = sub.fillna("")

        _, _, col2canon = resolve_headers(sub, user_map)
        mapped = len(col2canon)

        if mapped > best_mapped:
            best_mapped = mapped
            best_idx = i

    return best_idx


def load_all_sheets(path: Path, user_map: Dict[str, str]) -> dict[str, pd.DataFrame]:
    if path.suffix.lower() in {".xls", ".xlsx"}:
        raw_sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
        cleaned: Dict[str, pd.DataFrame] = {}

        for name, df0 in raw_sheets.items():
            header_idx = find_header_row(df0, user_map)
            header = df0.iloc[header_idx].fillna("").astype(str).tolist()
            data = df0.iloc[header_idx + 1 :].copy()
            data.columns = header
            cleaned[name] = data.fillna("")

        return cleaned

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str).fillna("")
        return {"": df}

    raise ValueError(f"Unsupported file type: {path.suffix}")


def generate_map(path: Path, out: Path, user_map: Dict[str, str], default_immediate: Dict[str, str]) -> None:
    all_sheets = load_all_sheets(path, user_map)
    mapping_out: Dict[str, Any] = {}

    for sheet_name, df in all_sheets.items():
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=str)
        hdr0 = find_header_row(raw, user_map)
        start_row = hdr0 + 1

        _, unknown_raw, col2canon = resolve_headers(df, user_map)
        canon2raw = {canon: raw for raw, canon in col2canon.items()}
        initial_missing_req = [c for c in REQ if c not in canon2raw]
        unused_canon = [c for c in ALL if c not in canon2raw]
        missing_req = list(initial_missing_req)

        sheet_cfg: Dict[str, Any] = {
            "mapping": canon2raw,
            "missing_required": [],
            "start_row": start_row,
        }

        immediate: Dict[str, str] = {}
        if "Form Name" not in canon2raw:
            immediate["Form Name"] = sheet_name
            if "Form Name" in missing_req:
                missing_req.remove("Form Name")

        for canon, val in default_immediate.items():
            if canon != "Form Name" and canon not in canon2raw:
                immediate[canon] = val
            if canon in missing_req:
                missing_req.remove(canon)

        sheet_cfg["missing_required"] = missing_req

        if immediate:
            sheet_cfg["immediate"] = immediate

        mapping_out[sheet_name] = sheet_cfg

        def bullet_list(items: List[str]) -> str:
            if not items:
                return "  - <none>"
            return "\n".join(f"  - {item}" for item in items)

        print(f"### Sheet `{sheet_name}`")
        print("Missing required (pre-defaults):")
        print(bullet_list(initial_missing_req))
        print("Unmapped raw columns:")
        print(bullet_list(unknown_raw))
        print("Unused canonical columns:")
        print(bullet_list(unused_canon))
        print()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapping_out, indent=2))
    print(f"Generated map for {len(mapping_out)} sheets → {out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate raw→canonical column maps")
    parser.add_argument("dict_file", help="Excel/CSV data dictionary to scan")
    parser.add_argument(
        "--out",
        dest="out_file",
        help="Destination for the generated JSON map (default: <DICT>-map.json)",
    )
    parser.add_argument(
        "--default-immediate",
        action="append",
        metavar="CANON=VALUE",
        help="Inject default values for missing canonical columns; repeatable",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    dict_path = Path(args.dict_file).resolve()
    if not dict_path.exists():
        sys.exit(f"ERROR: dictionary file not found: {dict_path}")

    if args.out_file:
        out_path = Path(args.out_file)
    else:
        out_path = dict_path.with_name(f"{dict_path.stem}-map.json")

    default_immediate: Dict[str, str] = {}
    if args.default_immediate:
        for tok in args.default_immediate:
            if "=" not in tok:
                sys.exit("ERROR: --default-immediate must be CANON=VALUE")
            canon, val = tok.split("=", 1)
            if canon not in ALL:
                sys.exit(f"ERROR: unknown canonical column '{canon}'")
            default_immediate[canon] = val

    generate_map(
        path=dict_path,
        out=out_path,
        user_map={},
        default_immediate=default_immediate,
    )


if __name__ == "__main__":
    main()
