# REDCap Pipeline Rollup Summary — Author & Ingest Leads

You will receive multiple stage summaries, each already formatted per the
transformation-summary template (Executive Summary, Structural Fixes,
Content Normalization, Upstream Guidance, etc.). Your task is to synthesize
these into one concise document that captures the overall remediation effort
for the data dictionary.

## HARD RULES
- Preserve chronological order of stages. The first stage is typically the
  structural remap (`map.py` / `reformat.py`); highlight this foundation before
  discussing later content edits.
- Do **not** repeat stage summaries verbatim. Collapse redundant bullets and
  focus on what changed across the entire pipeline.
- Keep the output between 350–650 words.
- Remap stage: emphasize canonical column coverage, sheet consolidation, and
  any default form assignments. Treat later “fix” stages as content
  normalization passes.
- If multiple stages apply the same kind of fix (e.g., text type cleanup,
  variable renaming), aggregate the counts and cite representative examples
  from the latest stage only.
- When metrics conflict or are missing from some stages, prefer concrete
  numbers; otherwise mark the metric as “unknown”. Never invent values.
- Do not introduce new field edits that are absent from the stage summaries.
- No markdown code fences except when quoting literal choice strings.

## INPUT
- A markdown document consisting of `### Stage N: <name>` headings followed by
  individual stage summaries.

## METHOD (internal reasoning steps)
1. Parse each stage summary and tag whether it is a **mapping** stage (only
   column/row operations) or a **content** stage (field types, choices,
   validations, renames).
2. Aggregate changes by theme across stages; prefer the latest metrics when
   stages overlap (e.g., type conversions repeated later override earlier
   numbers).
3. Identify 3–5 key takeaways spanning the entire pipeline.
4. Provide 3–6 upstream guidance bullets; when relevant, cite the stage in
   parentheses (e.g., “(Fix #2)”).
5. Compose a single Metrics block; if the stages report conflicting numbers,
   resolve if possible or state “unknown”.

## OUTPUT FORMAT
Follow the same headings as the individual summaries:

### Executive Summary (3–5 bullets)
- Focus on cross-stage impact (e.g., “Canonical remap + text normalization
  across 10 fields”).

### Structural Fixes (2–6 bullets)
- Cover mapping outcomes, sheet consolidation, form assignments, and any
  residual structural edits from later stages.

### Content Normalization (grouped by theme)
- Combine counts across stages (e.g., “Field types: 21 → text”).
- If no content-stage changes occurred, state “Not applicable (mapping-only
  pipeline).”

### Upstream Guidance for the Author (3–7 bullets)
- Provide consolidated, forward-looking guidance referencing the relevant
  stage (e.g., “(Fix #1)” or “(Remap)”).

### Risks & Follow-ups (optional, ≤ 3 bullets)
- Highlight open items that remain after all stages.

### Metrics (single block)
Fields changed: <N>; Types set: <N>; Choices normalized: <N>;
Validations set/cleared: <A>/<B>; Rows dropped: <K>.
Use concrete totals when available; otherwise “unknown”.

Return only this markdown report—no JSON block.
