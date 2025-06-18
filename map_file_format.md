# Map File Format Specification

This document describes the structure and fields of the JSON map file used by **redcap_format.py**.

## Top-level Structure

The map file is a JSON object where each key is the **sheet name** (string) and each value is a **sheet mapping object**.

```json
{
  "Sheet1": { ... },
  "OtherSheet": { ... }
}
```

## Sheet Mapping Object

Each sheet mapping object contains the following properties:

- **mapping** (object):  
  Maps canonical REDCap column names to raw column headers from the sheet.  
  ```json
  "mapping": {
    "Variable / Field Name": "RawVarName",
    "Field Label": "RawLabel",
    ...
  }
  ```

- **missing_required** (array of strings):  
  Lists canonical **required** headers (`REQ`) that were not auto-detected and not provided via defaults.  
  ```json
  "missing_required": ["Field Type", "Field Label"]
  ```

- **start_row** (integer):  
  1-based Excel row index where the header row was found.  
  ```json
  "start_row": 3
  ```

- **immediate** (object, optional):  
  Provides constant values to assign for canonical columns when missing or blank.  
  ```json
  "immediate": {
    "Form Name": "MyForm",
    "Field Type": "unknown"
  }
  ```

- **ignore** (boolean, optional):  
  If `true`, the sheet is skipped during the mapping application.  
  ```json
  "ignore": true
  ```

### Example Sheet Entry

```json
"Sheet1": {
  "mapping": {
    "Variable / Field Name": "VarCol",
    "Field Label": "LabelCol"
  },
  "missing_required": ["Field Type"],
  "start_row": 2,
  "immediate": {
    "Form Name": "Sheet1",
    "Field Type": "unknown"
  }
}
```

## Canonical REDCap Headers

- **Required (`REQ`)**:
  - Variable / Field Name
  - Form Name
  - Field Type
  - Field Label

- **Optional (`OPT`)**:
  - Section Header
  - Choices, Calculations, OR Slider Labels
  - Field Note
  - Text Validation Type OR Show Slider Number
  - Text Validation Min
  - Text Validation Max
  - Identifier?
  - Branching Logic
  - Required Field?
  - Custom Alignment
  - Question Number (surveys only)
  - Field Annotation
