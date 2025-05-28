<!-- Use the following reference doc for REDCap rules: redcap_reference.md -->
# REDCap Field Type Inference Prompt

You are an expert in REDCap data dictionaries. I will provide you
with two JSON files:

1. **map.json** – an object whose keys are the 16 canonical REDCap
   headers and whose values are:
   ```json
   { "fieldname": "<raw column name>", "override": <bool> }
   ```
   This tells you which raw column provided each canonical field.

2. **report.json** – an array of objects, one per line of the
   original sheet. Each object has:
   - `line`: the original sheet row number
   - `classification`: `{ "valid": <bool>, "error": <string|null> }`
   - the raw source values for:
     - `Variable / Field Name`
     - `Form Name`
     - `Field Type`
     - `Field Label`
     - `Choices, Calculations, OR Slider Labels`

## Task

For each entry in `report.json`, inspect its raw values (especially
the **Field Label** and the **Choices…** string) and infer the
correct REDCap **Field Type** from this list:
```
text, notes, radio, checkbox, dropdown, calc, file,
yesno, truefalse, slider, descriptive, date, datetime
```

Produce as output a JSON array of the same length, where each element
is the original object plus a new key:
```json
"inferred_field_type": "<one of the 13 canonical types>"
```

## Instructions

- If the original `Field Type` was invalid or missing, use the raw values
- to choose the best fit.
- If `Choices, Calculations, OR Slider Labels` is non-empty and contains
- exactly two values `0,No; 1,Yes`, you may infer `yesno`.
- If that column has more than two code-label pairs, choose `radio`
- (single-select), `checkbox` (multi-select), or `dropdown` as
- appropriate.
- If the label or **Choices…** mentions “slider” or numeric range, infer
- `slider`.
- If the label contains “file”, infer `file`.
- If it looks like a date format, infer `date` or `datetime` accordingly.
- Default to `text` when in doubt.

Return only the JSON array (no additional explanation).
