# REDCap Transformation DSL Primitives

1. `EnsureColumn(header)`  
   Create a column named `header` if it does not exist.

2. `RenameColumn(rawHeader, canonicalHeader)`  
   Rename an existing column `rawHeader` to `canonicalHeader`.

3. `SetFormName(rowNumber, formName)`  
   Populate the **Form Name** column on the given row.

4. `SetVariableName(rowNumber, newVariableName)`  
   Set `Variable / Field Name`. Automatically deduplicates by appending `_2`, etc.

5. `SetFieldType(rowNumber, fieldType)`  
   Set **Field Type**. One of:  
   `text, notes, radio, checkbox, dropdown, calc, file, yesno, truefalse, slider, descriptive, date, datetime`.

6. `SetChoices(rowNumber, [(code,label),…])`  
   For radio/checkbox/dropdown: fill **Choices, Calculations, OR Slider Labels**.

7. `SetSlider(rowNumber, min, minLabel, max, maxLabel)`  
   For slider: set numeric range and labels in **Choices, Calculations, OR Slider Labels**.

8. `SetFormula(rowNumber, formulaString)`  
   For calc fields: store the REDCap formula in **Choices, Calculations, OR Slider Labels**.

9. `SetFormat(rowNumber, formatString)`  
   For date/datetime: set format in **Text Validation Type OR Show Slider Number**.

10. `SetValidation(rowNumber, type, min, max)`  
    For text: set validation parameters in  
    **Text Validation Type OR Show Slider Number**, **Text Validation Min**, **Text Validation Max**.
