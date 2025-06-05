# REDCap Ingest & Transformation

This repository provides tools to lint, infer, compile fixes, and apply
transformations to a REDCap data dictionary, ensuring it conforms to REDCap's
specifications.

## Overview

Many organizations maintain data dictionaries that are almost, but not
entirely, compliant with REDCap requirements. This project automates the
process of identifying issues, inferring corrections, and applying fixes to
produce a fully compliant REDCap dictionary.

## Components

1. **redcap_lint.py**
   - Lints a REDCap data dictionary (CSV or XLSX).
   - Maps arbitrary column headers to canonical REDCap headers via synonyms,
     heuristics, and an optional `--map` file.
   - Produces `report.json`, detailing each row's classification (valid or
     violation) and raw values; and `map.json`, documenting header mappings
     and overrides.

2. **infer_submit.py**
   - Packages `report.json`, `map.json`, a prompt (`infer_prompt.md`), and a
     REDCap reference (`redcap_reference.md`).
   - Submits to the OpenAI API to infer the correct `Field Type` and generate
     a structured `configuration` for each row.
   - Handles chunking for large reports, token budgeting, and concatenates
     multiple responses into a single JSON array.
   - Outputs `augmented_report.json` with `inferred_field_type` and
     `configuration` fields added to each entry.

3. **compile_fixes.py**
   - Reads the original dictionary, `map.json`, and `augmented_report.json`.
   - Emits a DSL script (`fixes.rop`) consisting of primitive commands (e.g.,
     `SetFieldType`, `SetChoices`, `ClearCell`) needed to correct each row.
   - Ensures all required headers exist, applies header renames, and adds
     default yes/no choices or clears invalid cells when appropriate.

4. **apply_dsl.py**
   - Reads the original dictionary, `map.json`, and the DSL script
     (`fixes.rop`).
   - Executes each DSL primitive in order, transforming the DataFrame in
     memory.
   - Writes out the final, fully compliant REDCap dictionary (`NewDict.xlsx`)
     or CSV.

5. **redcap_convert_dsl.md**
   - Reference document listing all available DSL primitives and examples of
     their usage. Includes `ClearCell`, `SetChoices`, `SetValidation`, etc.

## Workflow

1. **Lint the dictionary**
   ```sh
   python redcap_lint.py DataDictionary.xlsx --report report.json
   ```
   - Produces `report.json` and `map.json`.

2. **Infer field types & configurations**
   ```sh
   python infer_submit.py --prompt infer_prompt.md \
       --reference redcap_reference.md --map map.json --report report.json \
       --output augmented_report.json
   ```
   - Generates `augmented_report.json`.

3. **Compile DSL commands**
   ```sh
   python compile_fixes.py --dict DataDictionary.xlsx \
       --map map.json --report augmented_report.json --output fixes.rop
   ```
   - Creates `fixes.rop` with primitive operations to correct the dictionary.

4. **Apply DSL script**
   ```sh
   python apply_dsl.py --dict DataDictionary.xlsx \
       --map map.json --ops fixes.rop --output NewDict.xlsx
   ```
   - Produces `NewDict.xlsx`, a fully REDCap-compliant dictionary.

## Requirements

- Python 3.8+
- pandas
- openpyxl
- tiktoken (for token counting)
- openai
- httpx

## Files

- `redcap_lint.py`
- `infer_submit.py`
- `compile_fixes.py`
- `apply_dsl.py` (alternate name: `fix.py`)
- `infer_prompt.md`
- `redcap_reference.md`
- `redcap_convert_dsl.md`

## Notes

- All JSON outputs (`report.json`, `augmented_report.json`, `map.json`) are
  pretty-printed for auditability.
- The DSL script (`fixes.rop`) is line-oriented; each line is a single
  primitive call.
- Operators should review `fixes.rop` before applying, to confirm that each
  primitive aligns with audit requirements.
