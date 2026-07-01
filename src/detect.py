"""
Detection stage: given a raw input (file path or URL), determine its
source_type so the right extractor can be dispatched.

Design note: detection is intentionally simple and rule-based (extension +
shallow content sniff). This keeps it deterministic and easy to explain -
no ML classification needed for this scope.
"""

import json
import os
import re


SOURCE_TYPES = {
    "recruiter_csv",
    "ats_json",
    "recruiter_notes",
    "github_profile",
    "unknown",
}


def detect_source_type(path_or_url: str) -> str:
    """
    Returns one of SOURCE_TYPES based on the input's shape.
    Never raises -- unknown/garbage input maps to 'unknown' so the
    pipeline can skip it gracefully rather than crash.
    """
    if not path_or_url or not isinstance(path_or_url, str):
        return "unknown"

    s = path_or_url.strip()

    if s.startswith("http://") or s.startswith("https://"):
        if "github.com" in s:
            return "github_profile"
        if "linkedin.com" in s:
            return "linkedin_profile"  # not implemented this round; detected for future extensibility
        return "unknown"

    # Accept a bare GitHub username as a convenience input.
    # Keep the heuristic narrow so ordinary free text does not get misclassified.
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", s):
        return "github_profile"

    if not os.path.isfile(s):
        return "unknown"

    ext = os.path.splitext(s)[1].lower()

    if ext == ".csv":
        return "recruiter_csv"

    if ext == ".json":
        # Distinguish a real ATS blob from garbage/unrelated JSON by a light content sniff.
        try:
            with open(s, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return "ats_json"
            return "unknown"
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return "unknown"  # malformed JSON -> treat as unknown/garbage, never crash

    if ext == ".txt":
        return "recruiter_notes"

    if ext in (".pdf", ".docx"):
        return "resume"  # not implemented this round; detected for future extensibility

    return "unknown"
