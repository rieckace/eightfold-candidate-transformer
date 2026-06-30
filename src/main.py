#!/usr/bin/env python3
"""
Multi-Source Candidate Data Transformer -- CLI

Usage:
    python3 main.py --inputs FILE [FILE ...] [--config CONFIG.json] [--out OUTPUT.json] [--verbose] [--report REPORT.json]

Examples:
    # Default schema, all sample sources
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv ../sample_inputs/ats_blob.json ../sample_inputs/recruiter_notes.txt

    # Custom config (subset fields, renamed, normalized)
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv ../sample_inputs/ats_blob.json ../sample_inputs/recruiter_notes.txt --config ../configs/example_config.json --out ../sample_outputs/custom_output.json

    # Verbose staged pipeline log + merge report
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv ../sample_inputs/ats_blob.json ../sample_inputs/recruiter_notes.txt --verbose --report ../sample_outputs/merge_report.json

    # Include a GitHub profile (bonus unstructured source, requires network)
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv https://github.com/rieckace
"""

import argparse
import json
import sys
import time

from pipeline import run_pipeline
from config import load_config, ConfigError
from projector import project, ProjectionError
from validate import validate_output
from reporting import print_pipeline_log, build_merge_report


def main():
    parser = argparse.ArgumentParser(description="Multi-Source Candidate Data Transformer")
    parser.add_argument("--inputs", nargs="+", required=True,
                         help="One or more input file paths or URLs (CSV, JSON, TXT, GitHub profile URL)")
    parser.add_argument("--config", default=None,
                         help="Path to a runtime output config JSON file. Omit for the default full schema.")
    parser.add_argument("--out", default=None,
                         help="Path to write the output JSON. Omit to print to stdout.")
    parser.add_argument("--verbose", action="store_true",
                         help="Print detect/extract run log to stderr.")
    parser.add_argument("--report", default=None,
                         help="Path to write a merge_report.json summarizing the run (candidates processed, fields merged, conflicts resolved, average confidence).")
    args = parser.parse_args()

    # --- Stage: detect -> extract -> normalize -> merge -> confidence ---
    start_time = time.time()
    try:
        canonical_records, run_log = run_pipeline(args.inputs, verbose=False)
    except Exception as e:
        print(f"FATAL: pipeline crashed unexpectedly: {e}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.time() - start_time

    if args.verbose:
        config_label = args.config if args.config else "default (full schema)"
        print_pipeline_log(run_log, canonical_records, elapsed, config_name=config_label)

    if not canonical_records:
        print("No candidate records could be built from the given inputs "
              "(all sources were missing, empty, or unrecognized).", file=sys.stderr)
        sys.exit(0)

    # --- Stage: load config ---
    config_dict = None
    if args.config:
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                config_dict = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"FATAL: could not read config file '{args.config}': {e}", file=sys.stderr)
            sys.exit(1)

    try:
        config = load_config(config_dict)
    except ConfigError as e:
        print(f"FATAL: invalid config: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Stage: project -> validate, per candidate ---
    results = []
    for rec in canonical_records:
        try:
            output = project(rec, config)
        except ProjectionError as e:
            print(f"FATAL: projection failed for candidate '{rec.candidate_id}': {e}", file=sys.stderr)
            sys.exit(1)

        is_valid, errors = validate_output(output, config)
        if not is_valid:
            print(f"WARNING: output for candidate '{rec.candidate_id}' failed validation:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)

        results.append(output)

    if args.report:
        report = build_merge_report(canonical_records, run_log, elapsed)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Merge report written to {args.report}", file=sys.stderr)

    final_output = results[0] if len(results) == 1 else results
    output_json = json.dumps(final_output, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Output written to {args.out}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
