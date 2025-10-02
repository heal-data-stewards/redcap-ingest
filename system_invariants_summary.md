# System Invariants (Transformation Summary)

- Produce **exactly two blocks**: (1) the Markdown report with the required headings; (2) the JSON object matching the schema.
- No extra prose before/between/after the two blocks. No code fences around the JSON object.
- If any field is unknown, set it to `null` or an empty list per schema; do **not** fabricate.
- Keep terminology consistent with the REDCap reference; do not rename fields/sections.
