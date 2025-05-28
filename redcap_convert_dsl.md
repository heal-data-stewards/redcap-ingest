# 1) Ensure that a column exists (add it if missing, blank by default)
EnsureColumn(canonicalHeader)

# 2) Rename raw header → canonical header
RenameColumn(rawHeader, canonicalHeader)

# 3) Set or correct the variable/field name on a specific row.
#    Automatically deduplicates by appending “_2”, “_3”, … if needed.
SetVariableName(rowNumber, newVariableName)

# 4) Set the field type on a specific row.
SetFieldType(rowNumber, fieldType)
    # fieldType must be one of:
    #   text, notes, radio, checkbox, dropdown, calc,
    #   file, yesno, truefalse, slider, descriptive, date, datetime

# 5) For multi-choice fields (radio/checkbox/dropdown/calc):
#    supply a list of (code,label) tuples.
SetChoices(rowNumber, [ (code1,label1), (code2,label2), … ])

# 6) For sliders:
SetSlider(rowNumber, minValue, minLabel, maxValue, maxLabel)

# 7) For calculated fields:
SetFormula(rowNumber, formulaString)

# 8) For date/datetime fields:
SetFormat(rowNumber, formatString)

# 9) For text fields:
SetValidation(rowNumber, validationType, validationMin, validationMax)
