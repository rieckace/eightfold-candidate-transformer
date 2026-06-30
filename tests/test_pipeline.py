"""
Tests for the Multi-Source Candidate Data Transformer.

Run with: python3 -m pytest tests/test_pipeline.py -v
       or: python3 tests/test_pipeline.py   (falls back to plain asserts)

Covers:
  - normalization correctness (phone, date, skill)
  - merge conflict resolution + confidence scoring
  - robustness against garbage/missing/empty sources (edge case)
  - config-driven projection (rename, normalize, omit, error)
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from normalize import normalize_phone, normalize_date, canonicalize_skill
from pipeline import run_pipeline
from config import load_config, ConfigError
from projector import project, ProjectionError
from validate import validate_output

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_inputs")


def test_normalize_phone_variants_converge():
    # Different raw formats of the "same" number should normalize identically.
    assert normalize_phone("098765-43210") == "+919876543210"
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("00 91 9876543210") == "+919876543210"


def test_normalize_phone_garbage_returns_none():
    assert normalize_phone("not a phone") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_normalize_date_formats():
    assert normalize_date("June 2023") == "2023-06"
    assert normalize_date("2023-06-15") == "2023-06"
    assert normalize_date("Present") == "present"
    assert normalize_date("garbage") is None


def test_canonicalize_skill_aliases():
    assert canonicalize_skill("js") == "JavaScript"
    assert canonicalize_skill("RL") is not None  # falls back gracefully even if not in alias map being exact-cased
    assert canonicalize_skill("") is None


def test_pipeline_merges_multi_source_into_single_candidate():
    """
    EDGE CASE: the same person appears across 3 sources (CSV has 2 rows
    for them, plus ATS JSON, plus recruiter notes) with conflicting email
    formats and phone formats. They must all collapse into ONE canonical
    record via shared email/phone match keys.
    """
    inputs = [
        os.path.join(SAMPLE_DIR, "recruiter_export.csv"),
        os.path.join(SAMPLE_DIR, "ats_blob.json"),
        os.path.join(SAMPLE_DIR, "recruiter_notes.txt"),
    ]
    records, log = run_pipeline(inputs)
    assert len(records) == 1, "Expected all sources to merge into a single candidate"
    rec = records[0]
    assert rec.full_name == "Rikesh Yadav"
    assert len(rec.emails) == 3  # 3 distinct emails surfaced across sources, none silently dropped
    assert "+919876543210" in rec.phones
    assert rec.overall_confidence > 0


def test_pipeline_robust_against_garbage_and_missing_sources():
    """
    EDGE CASE: garbage JSON, a nonexistent file, and an empty CSV must
    never crash the pipeline -- they should be silently skipped.
    """
    inputs = [
        os.path.join(SAMPLE_DIR, "recruiter_export.csv"),
        os.path.join(SAMPLE_DIR, "garbage_source.json"),
        os.path.join(SAMPLE_DIR, "does_not_exist.csv"),
        os.path.join(SAMPLE_DIR, "empty_source.csv"),
    ]
    records, log = run_pipeline(inputs)  # should not raise
    assert len(records) == 1  # only the valid CSV contributed data
    statuses = {entry["input"]: entry["status"] for entry in log}
    assert statuses[os.path.join(SAMPLE_DIR, "garbage_source.json")] == "empty_or_unrecognized"
    assert statuses[os.path.join(SAMPLE_DIR, "does_not_exist.csv")] == "empty_or_unrecognized"


def test_pipeline_deterministic():
    """
    CONSTRAINT: same inputs must produce the same output every run.
    """
    inputs = [
        os.path.join(SAMPLE_DIR, "recruiter_export.csv"),
        os.path.join(SAMPLE_DIR, "ats_blob.json"),
    ]
    records1, _ = run_pipeline(inputs)
    records2, _ = run_pipeline(inputs)
    assert records1[0].to_full_dict() == records2[0].to_full_dict()


def test_projection_example_config_from_assignment():
    """
    Reproduces the exact example config given in the assignment PDF and
    checks rename + E.164 normalize + skills canonicalization all work together.
    """
    inputs = [
        os.path.join(SAMPLE_DIR, "recruiter_export.csv"),
        os.path.join(SAMPLE_DIR, "ats_blob.json"),
        os.path.join(SAMPLE_DIR, "recruiter_notes.txt"),
    ]
    records, _ = run_pipeline(inputs)
    rec = records[0]

    cfg = load_config({
        "fields": [
            {"path": "full_name", "type": "string", "required": True},
            {"path": "primary_email", "from": "emails[0]", "type": "string", "required": True},
            {"path": "phone", "from": "phones[0]", "type": "string", "normalize": "E.164"},
            {"path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical"},
        ],
        "include_confidence": True,
        "on_missing": "null",
    })

    out = project(rec, cfg)
    assert out["full_name"] == "Rikesh Yadav"
    assert out["primary_email"] == "rikesh.yadav@example.com"
    assert out["phone"].startswith("+")
    assert isinstance(out["skills"], list) and "Python" in out["skills"]

    is_valid, errors = validate_output(out, cfg)
    assert is_valid, f"Validation errors: {errors}"


def test_projection_on_missing_error_raises():
    """
    EDGE CASE: a required field that resolves to nothing, with
    on_missing='error', must raise rather than silently produce bad output.
    """
    inputs = [os.path.join(SAMPLE_DIR, "recruiter_export.csv")]
    records, _ = run_pipeline(inputs)
    rec = records[0]

    cfg = load_config({
        "fields": [{"path": "ghost_field", "from": "links.linkedin", "type": "string", "required": True}],
        "on_missing": "error",
    })

    try:
        project(rec, cfg)
        assert False, "Expected ProjectionError to be raised"
    except ProjectionError:
        pass


def test_invalid_config_rejected():
    try:
        load_config({"fields": []})
        assert False, "Expected ConfigError for empty fields array"
    except ConfigError:
        pass


def test_confidence_formula_is_deterministic():
    """
    CONSTRAINT: the confidence formula itself (trust + agreement_bonus +
    validation_bonus - conflict_penalty) must be a pure function -- same
    inputs always produce the same score.
    """
    from merge import compute_confidence
    c1 = compute_confidence(0.8, agreeing_sources_count=2, validated=True, had_conflict=False)
    c2 = compute_confidence(0.8, agreeing_sources_count=2, validated=True, had_conflict=False)
    assert c1 == c2
    # Sanity-check the formula's direction of effect: agreement should raise
    # confidence, conflict should lower it, relative to the same base trust.
    base = compute_confidence(0.8, agreeing_sources_count=0, validated=False, had_conflict=False)
    with_agreement = compute_confidence(0.8, agreeing_sources_count=2, validated=False, had_conflict=False)
    with_conflict = compute_confidence(0.8, agreeing_sources_count=0, validated=False, had_conflict=True)
    assert with_agreement > base
    assert with_conflict < base
    assert compute_confidence(0.99, agreeing_sources_count=10, validated=True, had_conflict=False) <= 1.0


def test_provenance_includes_explainable_reason():
    """
    EDGE CASE: every populated field's provenance entry must include a
    non-empty, human-readable 'reason' string -- this is the merge
    explainability requirement, not just a source tag.
    """
    inputs = [
        os.path.join(SAMPLE_DIR, "recruiter_export.csv"),
        os.path.join(SAMPLE_DIR, "ats_blob.json"),
        os.path.join(SAMPLE_DIR, "recruiter_notes.txt"),
    ]
    records, _ = run_pipeline(inputs)
    rec = records[0]
    assert len(rec.provenance) > 0
    for p in rec.provenance:
        assert p.reason and len(p.reason) > 10, f"Provenance entry for '{p.field}' has no meaningful reason"
    # The full_name field specifically should mention agreement, since 4
    # sources all agree on the same name in our sample data.
    name_prov = next(p for p in rec.provenance if p.field == "full_name")
    assert "agreed" in name_prov.reason.lower() or "highest-trusted" in name_prov.reason.lower()


def _run_all():
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__} -> {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__} -> {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _run_all()
