"""
Professional pipeline logging + merge statistics report.

Two outputs:
  1. A staged console log (print_pipeline_log) shown when --verbose is set,
     replacing ad-hoc print statements with a consistent, readable format.
  2. A merge_report dict (build_merge_report) summarizing what happened --
     useful both as a console summary and as an optional JSON artifact
     (sample_outputs/merge_report.json) a reviewer can skim in seconds.
"""

import time


def print_pipeline_log(run_log, canonical_records, elapsed_seconds, config_name="default"):
    """Prints a structured, staged summary of what the pipeline did."""
    print("========== Candidate Pipeline ==========")

    print("\n[Detect / Extract]")
    for entry in run_log:
        status_mark = "PASS" if entry["status"] == "ok" else "SKIP"
        print(f"  [{status_mark}] {entry['input']}")
        print(f"         type={entry['detected_type']}  records_extracted={entry['records_extracted']}")

    total_extracted = sum(e["records_extracted"] for e in run_log)
    skipped = sum(1 for e in run_log if e["status"] != "ok")
    print(f"\n  Summary: {total_extracted} record(s) extracted from {len(run_log)} input(s), {skipped} source(s) skipped (missing/garbage/unrecognized).")

    print("\n[Merge]")
    print(f"  Candidate clusters formed: {len(canonical_records)}")
    for rec in canonical_records:
        fields_populated = sum(1 for p in rec.provenance)
        conflicts = sum(1 for p in rec.provenance if "Discarded conflicting" in p.reason or "deprioritized" in p.reason)
        print(f"    - {rec.candidate_id} ({rec.full_name or 'unnamed'}): "
              f"{fields_populated} provenance-tracked field(s), {conflicts} conflict(s) resolved, "
              f"overall_confidence={rec.overall_confidence:.2f}")

    print(f"\n[Projection]")
    print(f"  Applied profile: {config_name}")

    print(f"\n[Validation]")
    print(f"  Completed (see warnings above, if any)")

    print(f"\nRuntime: {elapsed_seconds:.3f} sec")
    print("=========================================")


def build_merge_report(canonical_records, run_log, elapsed_seconds):
    """
    Builds a structured merge_report summary -- the kind of artifact a
    reviewer can open and understand the pipeline's behavior in seconds,
    without reading the full output JSON.
    """
    sources_seen = sorted({e["detected_type"] for e in run_log if e["status"] == "ok"})
    total_extracted = sum(e["records_extracted"] for e in run_log)
    skipped_sources = [e["input"] for e in run_log if e["status"] != "ok"]

    candidates_report = []
    total_conflicts = 0
    total_fields_merged = 0
    all_confidences = []

    for rec in canonical_records:
        conflicts = sum(1 for p in rec.provenance if "Discarded conflicting" in p.reason or "deprioritized" in p.reason)
        fields_merged = len(rec.provenance)
        total_conflicts += conflicts
        total_fields_merged += fields_merged
        all_confidences.append(rec.overall_confidence)

        candidates_report.append({
            "candidate_id": rec.candidate_id,
            "full_name": rec.full_name,
            "merged_fields": fields_merged,
            "conflicts_resolved": conflicts,
            "sources_contributing": sorted({p.source for p in rec.provenance if "+" not in p.source}),
            "overall_confidence": rec.overall_confidence,
        })

    avg_confidence = round(sum(all_confidences) / len(all_confidences), 4) if all_confidences else 0.0

    return {
        "candidates_processed": len(canonical_records),
        "input_sources_seen": sources_seen,
        "sources_skipped": skipped_sources,
        "total_records_extracted": total_extracted,
        "merged_fields_total": total_fields_merged,
        "conflicts_resolved_total": total_conflicts,
        "average_confidence": avg_confidence,
        "runtime_seconds": round(elapsed_seconds, 4),
        "candidates": candidates_report,
    }
