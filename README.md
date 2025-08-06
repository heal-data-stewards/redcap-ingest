# REDCap‑Ingest

End‑to‑end utilities for upgrading a **quasi‑REDCap** data dictionary to a dictionary that REDCap will import without warnings.

---

## 1&nbsp;Prerequisites

* **Python ≥ 3.8**  
  Install dependencies once:

  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt         # pandas, openpyxl, httpx, openai, …
  ```

* **OpenAI API key**  
  Needed for the inference step ( `infer_submit.py` ):

  ```bash
  export OPENAI_API_KEY="sk‑yourkey"
  ```

---

## 2&nbsp;Quick‑start (copy & paste)

The snippet below runs the *entire* pipeline on `./OriginalDict.xlsx` and leaves you with `./FinalDict.xlsx`.

```bash
### 0  Prep ‑‑ create a throw‑away workspace
mkdir -p work && cd work
cp ../OriginalDict.xlsx .

### 1  Detect column → header mapping
python ../redcap_format.py OriginalDict.xlsx       --generate-map map.json

# 👉 Open map.json in an editor; fix any mismatches, then continue.

### 2  Draft structural fixes (rename columns, drop blank rows, …)
python ../reformat.py OriginalDict.xlsx       --map map.json       --dsl-out stage1.ops

### 3  Apply those fixes
python ../rcmod.py       --in OriginalDict.xlsx       --out Stage1Dict.xlsx       stage1.ops

### 4  Lint the result
python ../redcap_lint.py Stage1Dict.xlsx       --report lint.json

### 5  Ask GPT to complete missing info (Field Type, Choices, Validation)
python ../infer_submit.py       --report lint.json       --output augmented.json

### 6  Compile content‑level fixes
python ../fix.py       --dict Stage1Dict.xlsx       --report augmented.json       --output stage2.ops

### 7  Apply content fixes → 🎉 Final dictionary
python ../rcmod.py       --in Stage1Dict.xlsx       --out FinalDict.xlsx       stage2.ops
```

*Result:* `FinalDict.xlsx` should import into REDCap with zero warnings.

---

## 3&nbsp;Workflow in one glance

| # | Goal | Key script | Core output |
|---|------|------------|-------------|
| 1 | Detect column mapping | **redcap_format.py** | `map.json` |
| 2 | Draft structural DSL | **reformat.py** | `stage1.ops` |
| 3 | Apply structural fixes | **rcmod.py** | `Stage1Dict.xlsx` |
| 4 | Lint | **redcap_lint.py** | `lint.json` |
| 5 | Enrich lint via GPT | **infer_submit.py** | `augmented.json` |
| 6 | Compile content DSL | **fix.py** | `stage2.ops` |
| 7 | Apply content fixes | **rcmod.py** | `FinalDict.xlsx` |

Each `.ops` file is plain text—review or hand‑edit anytime.

---

## 4&nbsp;Scripts & what they do

| Script | What it does |
|--------|--------------|
| `redcap_format.py` | Scans a quasi‑REDCap dictionary, guesses which raw column belongs to each canonical REDCap header, and writes **`map.json`**. |
| `reformat.py` | Reads `map.json` and emits **DSL** commands to restructure columns / rows. |
| `rcmod.py` | Generic interpreter for the RCM DSL (`*.ops`). |
| `redcap_lint.py` | Validates a dictionary against REDCap rules; writes a per‑row JSON report. |
| `infer_submit.py` | Sends the lint report to GPT‑4o (or other OpenAI model) for auto‑completion of field metadata. |
| `fix.py` | Converts the augmented report into a second DSL script that fixes content errors (choices, validation, etc.). |

---

## 5&nbsp;Troubleshooting

* **Columns mapped wrong?**  Edit `map.json`, then restart from *Step 2*.  
* **LLM step too large?**  `infer_submit.py --chunks 4` splits the report into four smaller requests.  
* **Still failing linter?**  Open `lint.json`—look for `"error": "…"`. Fix manually or patch `stage2.ops`.

---

## 6&nbsp;License

MIT
