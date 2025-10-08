# REDCap-Ingest

Utilities for converting a quasi-REDCap data dictionary into a workbook
that REDCap will import without warnings, including automated column
normalisation, linting, LLM-assisted metadata inference, and DSL-based
replay of fixes.

## Quick Start
- **Dev Container:** Open in VS Code and choose *Reopen in Container* to
  get Python 3.11 with requirements preinstalled.
- **Local Python:** Use Python 3.11+, then install dependencies once:
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- **Minimal pipeline (run inside a scratch dir):**
  ```bash
  mkdir -p work && cd work
  cp ../OriginalDict.xlsx .
  python ../map.py OriginalDict.xlsx --out map.json
  # inspect map.json, add immediates, set ignore flags, then continue
  python ../reformat.py OriginalDict.xlsx --map map.json --out stage1.ops
  python ../rcmod.py --in OriginalDict.xlsx --out Stage1Dict.xlsx stage1.ops
  python ../redcap_lint.py Stage1Dict.xlsx --report lint.json || true
  python ../llm_submit.py --config ../job_infer.json \
    --source lint.json --io-dir . --key-file ~/.config/openai.key
  python ../fix.py --dict Stage1Dict.xlsx --report lint+.json \
    --output stage2.ops
  python ../rcmod.py --in Stage1Dict.xlsx \
    --out FinalDict.xlsx stage2.ops
  ```

## Pipeline Overview
1. `map.py --out ...`
   - **Input:** raw XLS/XLSX (multi-sheet allowed)
   - **Output:** `map.json` detailing sheet mappings, required field gaps,
     and optional constants (`immediate`).
2. `reformat.py --map ... --out ...`
   - **Input:** original dictionary + curated `map.json`
   - **Output:** `stage1.ops` DSL script that reproduces the mapping.
3. `rcmod.py --in ... stage1.ops`
   - **Input:** original dictionary + DSL
   - **Output:** single-sheet `Stage1Dict.xlsx` with canonical columns.
4. `redcap_lint.py --report lint.json`
   - **Input:** `Stage1Dict.xlsx`
   - **Output:** structured lint findings (`lint.json`) and exit code 2 on
     violations.
5. `llm_submit.py --config job_infer.json`
   - **Input:** `lint.json` (source payload) plus prompt/reference files
     listed in `job_infer.json`
   - **Output:** augmented lint (`lint+.json`) containing inferred field
     types and configurations.
6. `fix.py --dict Stage1Dict.xlsx --report lint+.json`
   - **Input:** stage-one dictionary + augmented lint
   - **Output:** `stage2.ops` DSL with content-level fixes.
7. `rcmod.py --in Stage1Dict.xlsx stage2.ops`
   - **Input:** stage-one dictionary + content DSL
   - **Output:** `FinalDict.xlsx` ready for import.
8. Optional: `llm_submit.py --config job_summary.json --source stage2.ops`
   to generate a Markdown change summary for authors and ingest staff.

**End-to-end example:**
```bash
python map.py Raw.xlsx --out tmp/map.json
python reformat.py Raw.xlsx --map tmp/map.json --out tmp/structure.ops
python rcmod.py --in Raw.xlsx --out tmp/Stage1.xlsx tmp/structure.ops
python redcap_lint.py tmp/Stage1.xlsx --report tmp/lint.json || true
python llm_submit.py --config job_infer.json --source tmp/lint.json \
  --io-dir tmp --key-env OPENAI_API_KEY
python fix.py --dict tmp/Stage1.xlsx --report tmp/lint+.json \
  --output tmp/content.ops
python rcmod.py --in tmp/Stage1.xlsx \
  --out Final.xlsx tmp/content.ops
```

## Script Reference
### map.py
Scans a quasi-REDCap dictionary and produces the JSON map consumed by later
steps.

```text
usage: map.py [-h] [--out OUT_FILE] [--default-immediate CANON=VALUE]
              dict_file

Generate raw→canonical column maps

positional arguments:
  dict_file             Excel/CSV data dictionary to scan

options:
  -h, --help            show this help message and exit
  --out OUT_FILE        Destination for the generated JSON map (default:
                        <DICT>-map.json)
  --default-immediate CANON=VALUE
                        Inject default values for missing canonical columns;
                        repeatable
```

Example:
```
python map.py Raw.xlsx --out tmp/map.json
```

### redcap_format.py
Applies a previously generated map to rebuild the dictionary with canonical
columns.

```text
usage: redcap_format.py [-h] --map MAP_FILE --output OUTPUT_FILE
                        [--elide-unlabeled]
                        dict_file

Apply a REDCap mapping JSON

positional arguments:
  dict_file             Original Excel workbook

options:
  -h, --help            show this help message and exit
  --map MAP_FILE        Path to map JSON
  --output OUTPUT_FILE  Destination XLSX to write
  --elide-unlabeled     Also drop rows lacking a Field Label
```

Example:
```
python redcap_format.py Raw.xlsx --map tmp/map.json --output tmp/Stage0.xlsx
```

### reformat.py
Builds a deterministic DSL (`*.ops`) equivalent to applying a `map.json`.

```text
usage: reformat.py [-h] [--map MAP_FILE] [--out OUT_FILE] [--elide-unlabeled]
                   dict_file

positional arguments:
  dict_file          Original Excel/CSV dictionary

options:
  -h, --help         show this help message and exit
  --map MAP_FILE     map.json produced by map.py (defaults to
                     <DICT>-map.json)
  --out OUT_FILE     Path to write the generated DSL (defaults to
                     <DICT>-reformat.rcm)
  --elide-unlabeled  Also delete rows with blank Field Label
```

Example:
```
python reformat.py Raw.xlsx --map tmp/map.json --out tmp/structure.ops
```

### rcmod.py
Executes DSL primitives over one or more sheets and writes the combined
output workbook.

```text
usage: rcmod.py [-h] --in INPUT_DICT --out OUTPUT_DICT ops_file

Apply DSL operations to REDCap dictionary

positional arguments:
  ops_file           DSL operations file

options:
  -h, --help         show this help message and exit
  --in INPUT_DICT    Original REDCap dictionary file (XLS/XLSX or CSV)
  --out OUTPUT_DICT  Output corrected dictionary file
```

Example:
```
python rcmod.py --in Raw.xlsx --out Stage1.xlsx structure.ops
```

### summarize_rcm.py
Runs `llm_submit.py` for each supplied DSL (`*.rcm`) file and concatenates the
stage summaries into a single markdown report.

```text
usage: summarize_rcm.py [-h] [--config CONFIG] [--rollup-config ROLLUP_CONFIG]
                        [--output OUTPUT] [--io-dir IO_DIR]
                        [--key-file KEY_FILE]
                        rcm_files [rcm_files ...]

Generate an aggregated summary for multiple RCM files.

positional arguments:
  rcm_files            Paths to *.rcm files in the order they should be
                        summarised

options:
  -h, --help           show this help message and exit
  --config CONFIG      Path to llm_submit job config (default: job_summary.json)
  --rollup-config ROLLUP_CONFIG
                        Path to llm_submit job config for the rollup stage
                        (default: job_summary_rollup.json)
  --output OUTPUT      Path for the combined markdown summary (default:
                        combined-summary.md inside --io-dir when provided)
  --io-dir IO_DIR      Override llm_submit --io-dir (defaults to current working
                        directory)
  --key-file KEY_FILE  Path to OpenAI API key file to pass through to llm_submit
```

Example:
```
python summarize_rcm.py stage1.rcm fixes/stage2.rcm \
  --output pipeline-summary.md
```

### split_forms.py
Splits the combined REDCap workbook into one workbook per form based on the
`Form Name` column. Files are named `<basename>-<form>.xlsx` and created only
when more than one form exists.

```text
usage: split_forms.py [-h] [--output-dir OUTPUT_DIR] input

Split REDCap dictionary by form

positional arguments:
  input                 Path to the consolidated REDCap workbook

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Directory to write per-form workbooks (defaults to
                        input directory)
```

Example:
```
python split_forms.py data/CTN0095A1/CTN0095A1-reformatted.xlsx
```

### redcap_lint.py
Validates canonical dictionaries, emitting a JSON lint report and non-zero
exit codes when violations occur.

```text
usage: redcap_lint.py [-h] [--report REPORT_FILE] [--form-name FORM_NAME]
                      dict_file

Lint a REDCap data dictionary.

positional arguments:
  dict_file             Path to REDCap data dictionary (CSV/XLS/XLSX)

options:
  -h, --help            show this help message and exit
  --report REPORT_FILE  Write detailed JSON lint report to this path
  --form-name FORM_NAME
                        Override every value in the 'Form Name' column
```

Example:
```
python redcap_lint.py Stage1.xlsx --report lint.json || true
```

### fix.py
Converts augmented lint output into DSL fixes for content (types, choices,
validations).

```text
usage: fix.py [-h] --dict DICT_FILE --report REPORT_FILE [-o OUT_FILE]

Compile DSL primitives from augmented report.json

options:
  -h, --help            show this help message and exit
  --dict DICT_FILE      Original REDCap dictionary (.csv or .xlsx)
  --report REPORT_FILE  Augmented report.json with inferred_field_type &
                        configuration
  -o OUT_FILE, --output OUT_FILE
                        Path to write DSL commands (defaults to stdout)
```

Example:
```
python fix.py --dict Stage1.xlsx --report lint+.json --output content.ops
```

### infer_submit.py
Legacy direct OpenAI submission helper that reads prompt/reference files
and a JSON lint report, then concatenates chunked completions.

```text
usage: infer_submit.py [-h] [--model MODEL] [--max-tokens MAX_TOKENS]
                       [--chunks CHUNKS] [--dry-run]
                       [--log-level {debug,info,warning,error,critical}]
                       [--prompt PROMPT] [--reference REFERENCE]
                       [--report REPORT] [--config CONFIG] [--output OUTPUT]

Submit REDCap inference prompt to the OpenAI API
```

Example (requires `infer_config.json` with an `api_key` field):
```
python infer_submit.py --report lint.json --output lint+.json
```

### llm_submit.py
Current, configurable OpenAI job runner with auto-chunking, templated
outputs, and support for JSON or text sources.

```text
usage: llm_submit.py [-h] --config CONFIG [--source SOURCE] [--model MODEL]
                     [--max-tokens MAX_TOKENS] [--temperature TEMPERATURE]
                     [--job-name JOB_NAME] [--io-dir IO_DIR] [--dry-run]
                     [--key-file KEY_FILE] [--key-env KEY_ENV]
                     [--log-level {debug,info,warning,error,critical}]
                     [--output OUTPUT] [--raw]

General OpenAI submission helper (auto-chunking, io-dir)
```

Examples:
```
python llm_submit.py --config job_infer.json --source lint.json --io-dir tmp
python llm_submit.py --config job_summary.json --source stage2.ops --io-dir tmp
```

## Configuration
- `map.json`: produced by `redcap_format.py`; see `map_file_format.md` for
  schema details.
- `job_infer.json` and `job_summary.json`: presets for `llm_submit.py`
  describing prompts, models, chunking headers, and output templates.
- `infer_prompt.md`, `summary.md`, `system_invariants_*.md`, and
  `redcap_reference.md`: prompt assets loaded by the job configs.
- `infer_submit.py` reads API keys from `--config` JSON (`{"api_key":
  "..."}`).
- `llm_submit.py` resolves API keys via `--key-file`, `--key-env`, or
  `OPENAI_API_KEY`.
- Devcontainer propagates `OPENAI_API_KEY` and optional `OPENAI_BASE_URL`
  from the host; replicate this locally as needed.

## File / Repo Layout
- `map.py`, `redcap_format.py`, `reformat.py`, `rcmod.py`, `split_forms.py`: structural mapping tools.
- `redcap_lint.py`, `fix.py`: linting and DSL generation for content fixes.
- `llm_submit.py`, `infer_submit.py`: LLM submission tooling.
- `job_*.json`, `infer_prompt.md`, `summary.md`, `summary_rollup.md`,
  `system_invariants_*.md`: prompt definitions and job presets.
- `redcap_reference.md`, `map_file_format.md`, `redcap_convert_dsl.md`:
  reference documentation for REDCap columns and DSL primitives.
- `.devcontainer/`: Python 3.11 container definition (Debian Bookworm).
- `requirements.txt`: pandas, openpyxl, openai, tiktoken runtime deps.
- `save/`: archival copies of earlier scripts (for comparison only).

## Changes Since Previous Version
- New `map.py` isolates JSON map generation; `redcap_format.py` now only
  applies existing maps.
- `apply_dsl.py` (see `save/rfi.py`) has been superseded by `rcmod.py`,
  which no longer requires `--map` at runtime.
- `compile_fixes.py` was renamed to `fix.py` and now always ensures
  `Section Header` exists before applying row fixes.
- `infer_submit.py` dropped `map.json` support; the modern replacement is
  `llm_submit.py` plus `job_infer.json`.
- New job workflow: `llm_submit.py` + `job_summary.json` produces an
  author-facing report from the generated DSL.

## Troubleshooting / Common Errors
- `redcap_format.py --map` exits if `--output` is omitted; pass an explicit
  path when normalising.
- `rcmod.py` only accepts XLS/XLSX inputs for multi-sheet processing; CSV
  sources must be converted first.
- `llm_submit.py` aborts if the config embeds `api_key`, `chunks`, or
  `source`; provide those at runtime instead.
- OpenAI quota errors show a usage summary via `quota_utils.summarize_usage`
  when available; check billing limits before retrying.

## Contributing & License
Contributions are welcome via pull request; document any new primitives or
job configs alongside code changes. Licensed under the MIT License.
