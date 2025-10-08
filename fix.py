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

MAX_VAR_NAME_LEN = 100  # REDCap allows up to 100 characters (≤26 recommended).


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sanitise_variable_name(raw: str) -> str:
    """Convert arbitrary text into a REDCap-friendly variable identifier."""
    cleaned = (raw or "").strip().lower()
    if not cleaned:
        return ""

    # Replace any non-alphanumeric characters with underscores and collapse runs.
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return ""

    # Variable names must start with a letter; prefix if necessary.
    if not cleaned[0].isalpha():
        cleaned = f"x_{cleaned}"

    # Enforce REDCap length constraint (<= MAX_VAR_NAME_LEN characters total).
    if len(cleaned) > MAX_VAR_NAME_LEN:
        cleaned = cleaned[:MAX_VAR_NAME_LEN]
        cleaned = cleaned.rstrip("_")
        if not cleaned:
            return ""
        if not cleaned[0].isalpha():
            cleaned = f"x_{cleaned}"
            if len(cleaned) > MAX_VAR_NAME_LEN:
                cleaned = cleaned[:MAX_VAR_NAME_LEN].rstrip("_")
                if not cleaned or not cleaned[0].isalpha():
                    return ""

    return cleaned

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

    ops = ['CreateOutputSheet("REDCap")']

    # 0) Load the REDCap sheet, starting at row 2
    ops.append('ProcessSheet("REDCap", 2)')

    # 1) Always ensure "Section Header" exists
    ops.append('EnsureColumn("Section Header")')

    # 2) Row-level fixes based on your augmented report
    VAR_RE = re.compile(fr'^[a-z][a-z0-9_]{{0,{MAX_VAR_NAME_LEN - 1}}}$')
    for entry in report:
        row = entry.get("line")
        inf_type = entry.get("inferred_field_type")
        cfg = entry.get("configuration", {})

        # Variable name correction
        orig_var = entry.get("Variable / Field Name", "")
        inferred_var = (entry.get("inferred_variable_name") or "").strip()
        classification = entry.get("classification") or {}
        raw_errors = classification.get("errors")
        if raw_errors is None:
            error_text = classification.get("error")
            if error_text:
                raw_errors = [part.strip() for part in error_text.split(";") if part.strip()]
            else:
                raw_errors = []
        issues_lower = [str(err).lower() for err in (raw_errors or []) if err]
        needs_invalid = any("invalid variable name" in err for err in issues_lower)
        needs_duplicate = any("duplicate variable name" in err for err in issues_lower)

        def emit_variable_name(candidate: str) -> bool:
            candidate = (candidate or "").strip()
            if not candidate:
                return False
            if VAR_RE.match(candidate):
                ops.append(f'SetVariableName({row}, "{candidate}")')
                return True
            cleaned = sanitise_variable_name(candidate)
            if cleaned and VAR_RE.match(cleaned):
                ops.append(f'SetVariableName({row}, "{cleaned}")')
                return True
            return False

        rename_emitted = False
        if inferred_var and (inferred_var != orig_var or needs_invalid or needs_duplicate):
            rename_emitted = emit_variable_name(inferred_var)

        if not rename_emitted and not VAR_RE.match(orig_var):
            lowered = orig_var.lower()
            if orig_var and lowered != orig_var and VAR_RE.match(lowered):
                ops.append(f'LowercaseVariableName({row})')
                rename_emitted = True
            else:
                rename_emitted = emit_variable_name(orig_var)

        if not rename_emitted and needs_invalid:
            rename_emitted = emit_variable_name(orig_var)
            if not rename_emitted and inferred_var:
                rename_emitted = emit_variable_name(inferred_var)

        if not rename_emitted and needs_duplicate:
            candidate = inferred_var or orig_var
            rename_emitted = emit_variable_name(candidate)
            if not rename_emitted and candidate != orig_var:
                rename_emitted = emit_variable_name(orig_var)

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
