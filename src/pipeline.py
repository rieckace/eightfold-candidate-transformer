"""
Pipeline orchestrator: wires detect -> extract -> merge for a given list
of input sources, returning the resulting CanonicalRecord(s).

(normalize is applied inside extractors/merge where relevant; confidence
is computed inside merge; project/validate are separate stages invoked
by the CLI after this, since they depend on runtime config.)
"""

from detect import detect_source_type
from extractors import extract
from merge import merge_records


def run_pipeline(input_paths, trust_weights=None, verbose=False):
    """
    input_paths: list of file paths or URLs/identifiers (e.g. github username)
    Returns: (list[CanonicalRecord], list[dict run_log entries])
    """
    all_records = []
    run_log = []

    for path in input_paths:
        source_type = detect_source_type(path)
        records = extract(source_type, path)

        run_log.append({
            "input": path,
            "detected_type": source_type,
            "records_extracted": len(records),
            "status": "ok" if records else "empty_or_unrecognized",
        })

        if verbose:
            print(f"[detect] {path} -> {source_type}")
            print(f"[extract] {len(records)} record(s) extracted")

        all_records.extend(records)

    canonical_records = merge_records(all_records, trust_weights=trust_weights)

    return canonical_records, run_log
