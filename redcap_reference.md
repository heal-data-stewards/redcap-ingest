# REDCap Dictionary Reference

This document defines the authoritative REDCap dictionary schema and field‐type
specifications. Include this reference whenever prompting an LLM to perform
transformations.

## Required Columns

All REDCap dictionaries **must** include these four columns:

1. **Variable / Field Name**  
   - Lowercase letters, numbers, or underscores; must start with a letter; max 100 chars (≤26 recommended).  
2. **Form Name**  
   - Name of the form or instrument.  
3. **Field Type**  
   - One of the valid types (see below).  
4. **Field Label**  
   - Human‐readable question text or prompt.

## Valid Field Types

Accepted values for **Field Type**:

- text  
- notes  
- radio  
- checkbox  
- dropdown  
- calc  
- file  
- yesno  
- truefalse  
- slider  
- descriptive  
- date  
- datetime  

### text
- **Description**: Single‐line free text.
- **Value format**: Any UTF‐8 string.
- **Required extras**: None beyond the four required columns.
- **Optional columns**:
  - Text Validation Type OR Show Slider Number
  - Text Validation Min
  - Text Validation Max

### notes
- **Description**: Multi‐line text area.
- **Value format**: Any UTF‐8 string.
- **Required extras**: None.
- **Optional columns**: None.

### radio
- **Description**: Single‐choice list (mutually exclusive).
- **Value format (Choices…)**: `code,label | code,label | …`
- **Required extras**:
  - Choices, Calculations, OR Slider Labels
- **Optional columns**: None.

### checkbox
- **Description**: Multi‐choice list.
- **Value format (Choices…)**: `code,label | code,label | …`
- **Required extras**:
  - Choices, Calculations, OR Slider Labels
- **Optional columns**: None.

### dropdown
- **Description**: Single‐choice dropdown menu.
- **Value format (Choices…)**: `code,label | code,label | …`
- **Required extras**:
  - Choices, Calculations, OR Slider Labels
- **Optional columns**: None.

### calc
- **Description**: Calculated field with formula.
- **Value format (Calculations)**: A REDCap formula, e.g. `[field1] + [field2]`.
- **Required extras**:
  - Choices, Calculations, OR Slider Labels
- **Optional columns**: None.

### file
- **Description**: File upload field.
- **Value format**: Blank or system‐populated file paths.
- **Required extras**: None.
- **Optional columns**: None.

### yesno
- **Description**: Yes/No binary choice.
- **Value format (Choices…)**: Implicit `1,Yes | 0,No`.
- **Required extras**: None.
- **Optional columns**: None.

### truefalse
- **Description**: True/False binary checkbox.
- **Value format**: `0` or `1`.
- **Required extras**: None.
- **Optional columns**: None.

### slider
- **Description**: Numeric slider control.
- **Value format (Choices…)**: `min,label | max,label` (e.g. `1,Poor | 5,Excellent`).
- **Required extras**:
  - Choices, Calculations, OR Slider Labels
- **Optional columns**:
  - Text Validation Type OR Show Slider Number

### descriptive
- **Description**: Read‐only explanatory text or HTML.
- **Value format**: Any HTML or plain text.
- **Required extras**: None.
- **Optional columns**: None.

### date
- **Description**: Date picker.
- **Value format**: `YYYY-MM-DD`.
- **Required extras**: None.
- **Optional columns**:
  - Text Validation Type OR Show Slider Number
  - Text Validation Min (`YYYY-MM-DD`)
  - Text Validation Max (`YYYY-MM-DD`)

### datetime
- **Description**: Date + time picker.
- **Value format**: `YYYY-MM-DD HH:MM` or `YYYY-MM-DD HH:MM:SS`.
- **Required extras**: None.
- **Optional columns**:
  - Text Validation Type OR Show Slider Number
  - Text Validation Min (`YYYY-MM-DD HH:MM`)
  - Text Validation Max (`YYYY-MM-DD HH:MM`)
