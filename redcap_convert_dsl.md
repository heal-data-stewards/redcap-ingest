
This document describes the primitive DSL commands that can be used to
transform a REDCap‐style data dictionary into a fully compliant REDCap
dictionary. Each command is written in a function-call style and operates
on a specific row or column.

## Primitives

1. **EnsureColumn(columnName)**
   Add a new (empty) column named `columnName` if it does not already
   exist. New cells will contain the empty string (`""`).

2. **RenameColumn(oldName, newName)**
   If a column header exactly matches `oldName` and `newName` is not
   already in use, rename `oldName` to `newName`.

3. **SetFormName(row, formName)**
   Overwrite the “Form Name” cell in the given 1-based `row` with the
   string `formName`. If the “Form Name” column does not exist, it is
   created first.

4. **SetVariableName(row, newName)**
   Overwrite the “Variable / Field Name” cell in the given 1-based
   `row` with `newName`. If `newName` already appears elsewhere in that
   column, append an underscore and a numeric suffix (`_2`, `_3`, …)
   until a unique name is found.

5. **SetFieldType(row, fieldType)**
   Overwrite the “Field Type” cell in the given 1-based `row` with
   `fieldType`, which must be one of:
   ```
   text, notes, radio, checkbox, dropdown, calc, file,
   yesno, truefalse, slider, descriptive, date, datetime
   ```

6. **ClearCell(row, columnName)**
   Overwrite the cell at 1-based `row` in column `columnName` with
   the empty string (`""`). If `columnName` does not exist yet, it is
   first created as an empty column, and then the cell is set to `""`.

7. **SetChoices(row, [ (code,label), … ])**
   Overwrite the “Choices, Calculations, OR Slider Labels” cell in the
   given 1-based `row` with a string of the form:
   ```
   code1,label1 | code2,label2 | …
   ```
   Each pair `(code,label)` is formatted as `code,label` and joined
   with `" | "`.

8. **SetSlider(row, minValue, "minLabel", maxValue, "maxLabel")**
   Overwrite the “Choices, Calculations, OR Slider Labels” cell in the
   given `row` with:
   ```
   minValue,minLabel | maxValue,maxLabel
   ```

9. **SetFormula(row, "formulaString")**
   Overwrite the “Choices, Calculations, OR Slider Labels” cell in the
   given `row` with the literal string
   ```
   formulaString
   ```
   (usually prefixed by `calc:` if desired, but the DSL does not enforce
   a specific prefix).

10. **SetFormat(row, "formatString")**
    Overwrite the “Text Validation Type OR Show Slider Number” cell in
    the given `row` with `formatString` (e.g. `date_ymd` or a
    datetime pattern). If the column does not exist, it is first created.

11. **SetValidation(row, "validationType", "minValue", "maxValue")**
    Populate three cells in the given `row`:
    - “Text Validation Type OR Show Slider Number” ← `validationType`
    - “Text Validation Min” ← `minValue`
    - “Text Validation Max” ← `maxValue`
    If any of these columns does not exist, it is first created.

12. **CreateOutputSheet(sheetName)**
    Initialize or clear the single destination sheet (`sheetName`) that
    will collect all processed rows. *Called exactly once* at script start.
    Name must be a valid sheet name

13. **ProcessSheet(sheetName, startRow)**
    Switch context to the source sheet `sheetName` and begin processing
    at the specified 1‑based header row (`startRow`). All subsequent
    commands apply to each data row and append directly to the output sheet.

14. **MapColumn(fromName, toName)**
    Record a mapping from a raw header `fromName` to a canonical header
    `toName`. This replaces the old `RenameColumn` to emphasize that
    mappings are not in‑place renames but logical associations used during
    processing.

15. **DeleteRowsIfEmpty([columnName1, columnName2, …])**
    Delete any row where *any* of the listed canonical columns is blank
    or consists only of whitespace. Use this to remove rows lacking a
    variable name and/or a field label.

16. **SetCell(row, columnName, value)**
    A catch‑all primitive for writing a constant `value` into the cell
    at 1‑based `row` and `columnName`. Creates the column if needed.

---

## Examples

```text
# Setting the output sheet name
CreateOutputSheet("REDCap")

# Ensure all required columns exist
EnsureColumn("Variable / Field Name")
EnsureColumn("Form Name")
EnsureColumn("Field Type")
EnsureColumn("Field Label")
EnsureColumn("Choices, Calculations, OR Slider Labels")
EnsureColumn("Text Validation Type OR Show Slider Number")
EnsureColumn("Text Validation Min")
EnsureColumn("Text Validation Max")

# Rename a raw header
RenameColumn("VarNameRaw", "Variable / Field Name")

# Map a column during output generation
ProcessSheet("Demographics", 3)
DeleteRowsIfEmpty(["Variable / Field Name", "Field Label"])
MapColumn("VarRaw", "Variable / Field Name")
EnsureColumn("Field Type")

# Set a custom form name on every row
SetFormName(2, "baseline_survey")
SetFormName(3, "baseline_survey")

# Ensure uniqueness of variable names
SetVariableName(5, "age")
SetVariableName(6, "age")       # becomes "age_2" if "age" already exists

# Change a field type to yesno and populate default choices
SetFieldType(8, yesno)
SetChoices(8, [("1","Yes"),("0","No")])

# Change a field type to radio with three options
SetFieldType(10, radio)
SetChoices(10, [("A","Option A"),("B","Option B"),("C","Option C")])

# Change a field to slider
SetFieldType(12, slider)
SetSlider(12, 0, "None", 10, "Extreme")

# Remove any residual choices when converting to text
SetFieldType(15, text)
ClearCell(15, "Choices, Calculations, OR Slider Labels")

# Set a calculation formula
SetFieldType(18, calc)
SetFormula(18, "[var1] + [var2]")

# Set date format hint
SetFieldType(21, date)
SetFormat(21, "YYYY-MM-DD")

# Set text validation range
SetFieldType(25, text)
SetValidation(25, "integer", "18", "99")
```
