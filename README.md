# Multi-Source Candidate Data Transformer

Built for the Eightfold Engineering Intern (Jul-Dec 2026) assignment.

**Author:** Rikesh Yadav (rikeshyadav2780@gmail.com)

Turns messy candidate data from multiple sources (recruiter CSVs, ATS exports,
free-text notes, GitHub profiles) into one clean, canonical, confidence-scored
profile — with full traceability of where every value came from.

---

## 1. What this does, in one breath

Feed it 1+ structured source and 1+ unstructured source for the same
candidate. It detects each source's type, extracts whatever it can from
each (without crashing on garbage), normalizes formats (phones → E.164,
dates → `YYYY-MM`, skills → canonical names), merges everything into one
record (resolving conflicts by source trust + cross-source agreement),
scores confidence per field, and finally reshapes the output into
whatever schema you ask for via a runtime config — no code changes needed.

---

## 2. Quick start (TL;DR)

```bash
git clone https://github.com/rieckace/eightfold-candidate-transformer.git
cd eightfold-candidate-transformer/src

# Run on the bundled sample inputs, default full schema, print to terminal
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/ats_blob.json \
                 ../sample_inputs/recruiter_notes.txt
```

That's it — no dependencies to install, no API keys, no config required.
Pure Python 3 standard library.

---

## 3. Project structure

```
eightfold-candidate-transformer/
├── src/
│   ├── main.py          # CLI entry point — start here
│   ├── pipeline.py       # orchestrates detect -> extract -> merge
│   ├── detect.py         # Stage 1: identifies source type from file/URL
│   ├── extractors.py     # Stage 2: parses each source type into a common shape
│   ├── normalize.py      # phone / date / skill normalization functions
│   ├── merge.py          # Stage 3+4: conflict resolution + confidence scoring
│   ├── models.py         # CanonicalRecord and related dataclasses (internal schema)
│   ├── config.py         # validates runtime output config
│   ├── projector.py       # Stage 5: reshapes canonical record per config
│   └── validate.py       # Stage 6: validates projected output against config
├── sample_inputs/        # mock candidate data across 3 source types + edge cases
├── sample_outputs/        # pre-generated outputs (default schema + custom config)
├── configs/               # example runtime config files
├── tests/
│   └── test_pipeline.py  # 10 tests covering normalization, merge, robustness, projection
└── README.md
```

**The pipeline, stage by stage** (mirrors the design doc):

```
detect → extract → normalize → merge → confidence → project → validate
```

| Stage | File | What it does |
|---|---|---|
| Detect | `detect.py` | Looks at a file extension or URL pattern and classifies it as `recruiter_csv`, `ats_json`, `recruiter_notes`, `github_profile`, or `unknown` |
| Extract | `extractors.py` | One function per source type, each parsing the raw format into a common intermediate dict. Never raises — garbage/missing input returns an empty list |
| Normalize | `normalize.py` | Phone → E.164, date → `YYYY-MM`, skill → canonical name via alias table. Garbage input returns `None`, never invented data |
| Merge | `merge.py` | Groups intermediate records into one cluster per real candidate (matched by shared email/phone), resolves conflicts using source trust weights + cross-source agreement, builds the final `CanonicalRecord` with full provenance |
| Confidence | (inside `merge.py`) | Per-field and overall confidence scores, based on source trust + how many independent sources agreed |
| Project | `projector.py` | Reshapes the full canonical record into whatever subset/rename/normalize the runtime config asks for |
| Validate | `validate.py` | Checks the projected output actually matches the requested schema before returning it |

---

## 4. Running it — all the ways

### 4.1 Default output (full canonical schema)

```bash
cd src
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/ats_blob.json \
                 ../sample_inputs/recruiter_notes.txt
```

### 4.2 Custom config (subset fields, renamed, normalized)

This reproduces the exact example config from the assignment PDF —
select fields, rename `emails[0]` → `primary_email`, normalize phone to
E.164, normalize skills to canonical names:

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/ats_blob.json \
                 ../sample_inputs/recruiter_notes.txt \
                 --config ../configs/example_config.json
```

See `configs/example_config.json` to see the config shape, or write your own —
any JSON file matching that structure works.

### 4.3 Save output to a file instead of printing

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/ats_blob.json \
                 --out ../sample_outputs/my_output.json
```

### 4.4 Verbose mode (see what detect/extract did for each source)

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/garbage_source.json \
                 --verbose
```

This prints a run log showing exactly what type each input was detected
as, how many records were extracted, and whether each source contributed
data or was gracefully skipped.

### 4.5 Including the GitHub profile source (bonus, needs network)

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 https://github.com/rieckace
```

This calls the real public GitHub REST API. If you have no network
access (or hit a rate limit), the pipeline does **not** crash — the
GitHub source is silently skipped and the rest of the merge proceeds
normally. This is intentional: see Constraint #2 ("Robust") in the design doc.

### 4.6 Running the tests

```bash
# from the repo root
python3 tests/test_pipeline.py

# or, if you have pytest installed
python3 -m pytest tests/test_pipeline.py -v
```

10 tests, all passing, covering: normalization correctness, multi-source
merge + conflict resolution, robustness against garbage/missing/empty
sources, determinism, and config-driven projection (including the exact
example config from the assignment and the `on_missing: error` path).

---

## 5. Sample inputs included (and why each one exists)

| File | Source type | Why it's interesting |
|---|---|---|
| `recruiter_export.csv` | structured | Same candidate appears in 2 rows with a different email and phone format each time — tests dedup/merge |
| `ats_blob.json` | structured | Field names deliberately don't match our schema (`fullName`, `mobile`, `org`, `addr.nation`) — tests the extractor's remapping logic, plus a non-ISO country name ("Taiwan") that needs conversion to `TW` |
| `recruiter_notes.txt` | unstructured | Free text with an explicit "preferred email" cue that conflicts with an "old/inactive" email, skills buried in a parenthetical aside, education buried mid-paragraph — tests pattern-based extraction |
| `garbage_source.json` | — | Deliberately malformed JSON — tests that a broken source never crashes the run |
| `empty_source.csv` | — | Zero-byte file — tests the empty-source edge case |

Running the full set together produces **one merged candidate** (not five
separate ones) because the match key (shared email/phone) correctly
clusters all valid records together, while the two broken sources are
silently skipped.

---

## 6. Design decisions worth knowing (full reasoning in the design PDF)

- **Match key for merging:** shared normalized email OR phone. Name alone
  is deliberately *not* used as a match key (too many false-positive risks
  with common names) — documented trade-off under time pressure.
- **Source trust weights** (used to resolve scalar-field conflicts):
  `resume: 0.9 > ats_json: 0.8 > recruiter_csv: 0.75 > linkedin: 0.7 > github: 0.6 > recruiter_notes: 0.5`
  Configurable via `merge.DEFAULT_TRUST_WEIGHTS`.
- **List fields** (emails, phones, skills, education) are unioned and
  deduped, never overwritten — we never silently drop a value a real
  source gave us.
- **Confidence** = source trust weight, boosted +0.15 if 2+ independent
  sources agree on the same value (capped at 1.0).
- **No external dependencies.** Phone normalization is a self-contained
  heuristic (not the full `phonenumbers` library) so the tool runs
  anywhere with zero install friction — a deliberate scope trade-off
  given the time constraint.
- **LinkedIn / resume (PDF/DOCX) extractors are not implemented** this
  round, but the extractor interface (`extract(source_type, path) -> list[dict]`)
  is built so adding either is a drop-in addition, not a redesign.

For the full design rationale — pipeline breakdown, merge policy, 3-5 edge
cases, and what was deliberately descoped — see the one-page design
document submitted alongside this repo.

---

## 7. Assumptions & what's out of scope

- Sample inputs are mocked (the assignment provided no sample data) —
  built deliberately messy to exercise merge conflicts and robustness.
- Resume (PDF/DOCX) parsing is not implemented — recruiter notes (.txt)
  was chosen as the primary unstructured source instead, since it's
  explicitly listed as an equally valid option in the assignment, and
  keeps the tool fully offline/dependency-free for grading reliability.
  GitHub profile extraction is included as a bonus live-API source.
- LinkedIn extraction is not implemented (no public API without auth/scraping).
- This has been tested on a handful of mock candidates, not benchmarked
  at "thousands of candidates" scale — the design (no global state,
  linear pass over input list, dict-based clustering) should scale
  reasonably, but this wasn't load-tested given the time constraint.
