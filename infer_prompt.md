<!-- Use the following reference doc for REDCap rules: redcap_reference.md -->

# REDCap Field Type & Configuration Inference Prompt

You are an expert in REDCap data dictionaries. I will provide you with
two JSON files:

1. **map.json** – an object whose keys are the 16 canonical REDCap headers
   and whose values are:
   ```json
   { "fieldname": "<raw column name>", "override": <bool> }
   ```
   This tells you which raw column provided each canonical field.

2. **report.json** – an array of objects, one per line of the original
   sheet. Each object has:
   - `line`: the original sheet row number
   - `classification`: `{ "valid": <bool>, "errors": [<string>, ...], "error": <string|null> }`
   - the raw source values for:
     - `Variable / Field Name`
     - `Form Name`
     - `Field Type`
     - `Field Label`
     - `Choices, Calculations, OR Slider Labels`

## Task

For each entry in `report.json`:

1. **Infer** the correct REDCap **Field Type** from this list:
   ```
   text, notes, radio, checkbox, dropdown, calc, file,
   yesno, truefalse, slider, descriptive, date, datetime
   ```

2. **Extract** and **structure** a **configuration** object for each:
   - Always include a `"configuration"` property (never omit it).
   - **yesno**, **truefalse**, **notes**, **file**, **descriptive**
     ```json
     "configuration": {}
     ```
   - **yesno** when any of these is true:
     1. `"Choices, Calculations, OR Slider Labels"` has exactly two
        pairs with labels yes/no (case-insensitive).
     2. `"Choices, Calculations, OR Slider Labels"` is empty and
        `Field Label` poses a question that would be answered
        with a "yes" or "no".
     ```json
     "configuration": [
       { "code": "1", "label": "Yes" },
       { "code": "0", "label": "No" }
     ]
     ```
   - **radio**, **checkbox**, **dropdown**
     ```json
     "configuration": {
       "choices": [
         { "code": "<code1>", "label": "<label1>" },
         { "code": "<code2>", "label": "<label2>" },
         …
       ]
     }
     ```
   - **slider**
     ```json
     "configuration": {
       "min": <numeric_min>, "min_label": "<label_for_min>",
       "max": <numeric_max>, "max_label": "<label_for_max>"
     }
     ```
   - **calc**
     ```json
     "configuration": {
       "formula": "<REDCap_formula_string>"
     }
     ```
   - **date** or **datetime**
     ```json
     "configuration": {
       "format": "<expected_format_string>"
     }
     ```
   - **text**
     ```json
     "configuration": {
       "validation_type": "<Text Validation Type or Show Slider Number>",
       "min": "<Text Validation Min>", "max": "<Text Validation Max>"
     }
     ```

3. **Produce** a JSON array of the same length, where each element is the
   original object plus these new keys:
   ```json
   "inferred_field_type": "<one of the 13 canonical types>",
   "configuration": <appropriate object or array>,
   "inferred_variable_name": "<canonical variable identifier>"
   ```
   Set `"inferred_variable_name"` to a compliant identifier even when the
   original value was already valid (simply repeat it). When the source value
   is invalid, supply the corrected identifier you expect the ingest pipeline
   to use.

## Rules

- Always fix rows where `"classification.valid"` is `false`.
- Review every entry in `"classification.errors"`; rows may report multiple issues that all need corrections.
- Every `"Variable / Field Name"` in the output must be a valid REDCap
  identifier: lowercase, 1–100 characters, start with a letter, and only
  contain letters, digits, or underscores (≤26 recommended for readability). If the input value violates
  the rules, rewrite it into a compliant identifier (e.g. replace spaces
  with underscores, drop punctuation, prefix with a letter if needed).
- If `"Choices, Calculations, OR Slider Labels"` has exactly two
  code/label pairs with labels yes/no, infer `yesno` and structure
  its configuration.
- If `"Choices, Calculations, OR Slider Labels"` is empty and
  `Field Label` poses a question that would be answered with a
  "yes" or "no", infer `yesno` and populate default yes/no
  configuration.
- If `Field Label` poses a yes/no question but
  `"Choices, Calculations, OR Slider Labels"` exists with labels not
  strictly yes/no, infer `radio` and list choices.
- If `"Choices, Calculations, OR Slider Labels"` has two non-boolean
  options, infer `radio`.
- Parse `"Choices, Calculations, OR Slider Labels"` into structured
  arrays for choice-based types.
- Derive slider min/max and labels into `configuration`.
- Extract calc formulas into `configuration`.
- Infer date/datetime formats into `configuration`.
- If none of the above rules apply, assume text.
- Return **only** the JSON array (no additional explanation).
