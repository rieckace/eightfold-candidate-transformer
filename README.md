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
scores confidence per field via a deterministic formula, and finally
reshapes the output into whatever schema you ask for via a runtime
config — no code changes needed.

```
  Recruiter CSV   ATS JSON   Recruiter Notes   GitHub Profile
        │             │             │                │
        └─────────────┴──────┬──────┴────────────────┘
                              ▼
                      Source Detection
                              ▼
                         Extraction
                              ▼
                    Common Intermediate Shape
                              ▼
                       Normalization
                    (phone / date / skill)
                              ▼
                        Merge Engine
                (match-key clustering, trust-weighted
                   conflict resolution, dedup)
                              ▼
                  Deterministic Confidence
              (trust + agreement + validation − conflict)
                              ▼
                     Canonical Record
                   (full-fidelity, internal)
                              ▼
                    Projection (runtime config)
              (subset / rename / normalize / on_missing)
                              ▼
                         Validation
                              ▼
                        Output JSON
```

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
│   ├── validate.py       # Stage 6: validates projected output against config
│   └── reporting.py      # structured pipeline logging + merge_report.json builder
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

### 4.4 Verbose mode — staged pipeline log

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/ats_blob.json \
                 ../sample_inputs/recruiter_notes.txt \
                 ../sample_inputs/garbage_source.json \
                 --verbose
```

Prints a structured, staged log (Detect/Extract → Merge → Projection →
Validation) showing exactly what type each input was detected as, how
many records were extracted, how many candidate clusters formed, how
many conflicts were resolved, and the overall confidence — not raw
prints, a readable run summary.

### 4.5 Merge report — machine-readable run summary

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 ../sample_inputs/ats_blob.json \
                 ../sample_inputs/recruiter_notes.txt \
                 --report ../sample_outputs/merge_report.json
```

Writes a `merge_report.json` with candidates processed, fields merged,
conflicts resolved, sources contributing, and average confidence — a
reviewer can understand what the pipeline did without reading the full
candidate JSON.

### 4.6 Including the GitHub profile source (bonus, needs network)

```bash
python3 main.py --inputs ../sample_inputs/recruiter_export.csv \
                 https://github.com/rieckace
```

This calls the real public GitHub REST API. If you have no network
access (or hit a rate limit), the pipeline does **not** crash — the
GitHub source is silently skipped and the rest of the merge proceeds
normally. This is intentional: see Constraint #2 ("Robust") in the design doc.

### 4.7 Running the tests

```bash
# from the repo root
python3 tests/test_pipeline.py

# or, if you have pytest installed
python3 -m pytest tests/test_pipeline.py -v
```

12 tests, all passing, covering: normalization correctness, multi-source
merge + conflict resolution, robustness against garbage/missing/empty
sources, determinism, config-driven projection (including the exact
example config from the assignment and the `on_missing: error` path),
the deterministic confidence formula, and provenance explainability
(every populated field carries a non-empty, human-readable `reason`).

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

## 6. Confidence formula & provenance

Every populated field's confidence is computed by one deterministic,
auditable formula (in `merge.py`):

```
confidence = min(1.0, source_trust + agreement_bonus + validation_bonus - conflict_penalty)

  source_trust       = trust weight of the winning source (0-1; see table below)
  agreement_bonus     = +0.03 per OTHER independent source agreeing on the same value
  validation_bonus    = +0.02 if the value passed format validation
  conflict_penalty    = -0.10 if at least one other source disagreed
```

Source trust weights: `resume 0.9 > ats_json 0.8 > recruiter_csv 0.75 >
linkedin 0.7 > github 0.6 > recruiter_notes 0.5` (configurable via
`merge.DEFAULT_TRUST_WEIGHTS`).

Every populated field also carries a full `Provenance` entry — not just
*which* source won, but *why*:

```json
{
  "field": "phones[0]",
  "source": "recruiter_csv",
  "method": "merged_union+normalized",
  "reason": "Normalized to E.164 from 'recruiter_csv'. Confirmed by 2 other source(s) after normalization."
}
```

`overall_confidence` is the average of every populated field's
confidence — so it reflects the actual evidence behind the record, not
an arbitrary single number.

---

## 7. Design Decisions

**Why a canonical model separate from the output?** Sources disagree, use
different field names, and arrive in different shapes. Building one
internal, full-fidelity `CanonicalRecord` first — and only shaping it into
the requested output at the very end — means the merge logic never has to
think about what the caller asked for, and the projection logic never has
to think about where data came from. Each stays simple and testable on
its own.

**Why a projection layer instead of just filtering the canonical dict?**
The assignment's runtime config does more than filtering — it renames
fields, applies per-field normalization, and has three different
missing-value behaviors. Centralizing that in one `project()` function
means every output shape (default schema, a recruiter-specific view, a
minimal API response) is generated by the same code path, so a bug fixed
once is fixed everywhere.

**Why a deterministic confidence formula instead of hardcoded scores?**
A reviewer (or a future engineer) should be able to recompute any
confidence value by hand from the formula and the inputs. Every number
traces back to a specific, inspectable fact about the merge (which
source won, how many others agreed, whether the value passed format
validation, whether anything disagreed) — see Section 6.

**Why provenance with a `reason` string, not just a source tag?** Knowing
*that* a value came from `ats_json` is a fraction of the story. Knowing
*why* `ats_json` was chosen over `recruiter_notes` — and what alternative
values were discarded — is what actually makes the output trustworthy
and debuggable. Every populated field carries this.

**Why a CLI, not a UI?** The assignment explicitly deprioritizes the
input/output surface relative to engine correctness. A CLI is the
fastest way to expose the full pipeline (including the run log, merge
report, and config flexibility) without spending time on presentation
that doesn't affect correctness.

**Why a deterministic merge (no fuzzy matching / ML)?** Matching on
exact normalized email/phone, and resolving conflicts by a fixed trust
table, means the same inputs always produce the same output — a hard
constraint in the brief — and every decision can be explained in one
sentence. Fuzzy name-matching or ML-based merging would add real value
at production scale, but also add nondeterminism and unexplainable edge
cases that aren't worth the risk under this assignment's time and
correctness priorities.

**Why LinkedIn / resume (PDF/DOCX) extractors aren't implemented this
round.** The extractor interface (`extract(source_type, path) ->
list[dict]`) is built so adding either is a drop-in addition, not a
redesign — but writing a robust PDF/DOCX parser, or handling LinkedIn's
lack of a public API, was judged lower-value than hardening the
merge/confidence/projection core under the time constraint.

**Why no external dependencies (e.g. `phonenumbers`).** Phone
normalization is a self-contained heuristic so the tool runs anywhere
with zero install friction — a deliberate scope trade-off, trading
perfect international coverage for grading reliability.

For the full design rationale — pipeline breakdown, merge policy, 3-5 edge
cases, and what was deliberately descoped — see the one-page design
document submitted alongside this repo.

---

## 8. Assumptions & what's out of scope

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
