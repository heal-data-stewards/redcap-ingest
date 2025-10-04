# System Invariants (Pipeline Rollup Summary)

- Produce exactly one markdown document with the prescribed headings; do not
  return JSON or auxiliary blocks.
- Keep headings in the specified order and omit any section only if it is
  explicitly marked “optional”.
- No preface or epilogue text outside of the requested sections.
- When metrics are unknown, write the literal word `unknown`.
- Maintain consistent terminology with the stage summaries (e.g., use
  “Structural Fixes”, “Content Normalization”).
