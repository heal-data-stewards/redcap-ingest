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
   - `classification`: `{ "valid": <bool>, "error": <string|null> }`
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

2. **Extract** and **structure** any **configuration** details needed to
   fully define that field type:
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
       "min": <numeric_min>,
       "min_label": "<label_for_min>",
       "max": <numeric_max>,
       "max_label": "<label_for_max>"
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
       "validation_type": "<Text Validation Type OR Show Slider
       Number>",
       "min": "<Text Validation Min>",
       "max": "<Text Validation Max>"
     }
     ```
   - **yesno**, **truefalse**, **notes**, **file**, **descriptive**
     ```json
     "configuration": {}
     ```

3. **Produce** a JSON array of the same length, where each element is the
   original object plus these new keys:
   ```json
   "inferred_field_type": "<one of the 13 canonical types>",
   "configuration": { … }
   ```

## Rules

- Always fix rows where `"classification.valid"` is `false`.
- Parse `"Choices, Calculations, OR Slider Labels"` into structured
  code/label pairs for choice-based types.
- Derive numeric min/max and labels for sliders from that same string.
- Extract any REDCap formulas for `calc` types.
- Infer date/datetime formats from label or context (e.g. `YYYY-MM-DD`).
- Default to `"text"` with empty configuration when in doubt.
- Return **only** the JSON array (no additional explanation).
