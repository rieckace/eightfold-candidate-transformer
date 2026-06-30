#!/usr/bin/env python3
"""
Multi-Source Candidate Data Transformer -- CLI

Usage:
    python3 main.py --inputs FILE [FILE ...] [--config CONFIG.json] [--out OUTPUT.json] [--verbose]

Examples:
    # Default schema, all sample sources
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv ../sample_inputs/ats_blob.json ../sample_inputs/recruiter_notes.txt

    # Custom config (subset fields, renamed, normalized)
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv ../sample_inputs/ats_blob.json ../sample_inputs/recruiter_notes.txt --config ../configs/example_config.json --out ../sample_outputs/custom_output.json

    # Include a GitHub profile (bonus unstructured source, requires network)
    python3 main.py --inputs ../sample_inputs/recruiter_export.csv https://github.com/rieckace
"""

import argparse
import json
import sys

from pipeline import run_pipeline
from config import load_config, ConfigError
from projector import project, ProjectionError
from validate import validate_output


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
    args = parser.parse_args()

    # --- Stage: detect -> extract -> normalize -> merge -> confidence ---
    try:
        canonical_records, run_log = run_pipeline(args.inputs, verbose=args.verbose)
    except Exception as e:
        print(f"FATAL: pipeline crashed unexpectedly: {e}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print("\n--- Run log ---", file=sys.stderr)
        print(json.dumps(run_log, indent=2), file=sys.stderr)

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
