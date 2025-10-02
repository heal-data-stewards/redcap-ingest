# System Invariants (Field-Type Inference)

- Respond with **only a JSON array**; no prose, no code fences, no trailing commas.
- Do not invent values. If unknown/unsure, use an empty string or omit the key as specified by the schema.
- Apply identical normalization rules across **all chunks** in this run (codes, labels, date formats).
- Preserve stable ordering when meaningful; otherwise, do not reorder items arbitrarily.
- Never echo the prompt or input back.
