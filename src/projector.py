"""
Projection stage: takes a fully-built CanonicalRecord (internal,
full-fidelity) and a validated config (see config.py), and produces the
OUTPUT dict the config actually asked for.

This is the layer that implements the assignment's "required twist":
  - select a subset of fields
  - rename/remap a field from a canonical path (the "from" key)
  - per-field normalization
  - toggle provenance/confidence
  - configurable missing-value behavior (null / omit / error)

Path resolution supports a small dotted/bracket syntax sufficient for the
schema's shape: "emails[0]", "skills[].name", "location.city", etc.
We deliberately do NOT build a full JSONPath engine -- that's overkill
for this fixed schema and would cost time without adding real value.
This is a documented scope decision.
"""

import re
from normalize import normalize_phone, canonicalize_skill


class ProjectionError(Exception):
    """Raised when on_missing='error' and a required field is missing."""
    pass


_INDEX_RE = re.compile(r"^([a-zA-Z_]+)(\[(\d*)\])?$")


def _resolve_path(record_dict, path):
    """
    Resolves a dotted/bracket path against the full canonical dict.
    Supports:
      "full_name"          -> record_dict["full_name"]
      "emails[0]"           -> record_dict["emails"][0]
      "location.city"       -> record_dict["location"]["city"]
      "skills[].name"       -> [s["name"] for s in record_dict["skills"]]
    Returns None if any segment is missing/out-of-range (never raises --
    missing-value handling is the caller's job via on_missing).
    """
    current = record_dict
    segments = path.split(".")

    for seg in segments:
        if current is None:
            return None

        m = _INDEX_RE.match(seg)
        if not m:
            return None  # malformed path segment -> treat as missing

        key, has_index, index_str = m.group(1), m.group(2), m.group(3)

        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]

        if has_index:
            if index_str == "":
                # Bare "key[]" with nothing after it just returns the list itself.
                # The "key[].subfield" case is handled separately by
                # _resolve_list_projection before this function is ever called.
                if not isinstance(current, list):
                    return None
                return current
            else:
                idx = int(index_str)
                if not isinstance(current, list) or idx >= len(current):
                    return None
                current = current[idx]

    return current


def _resolve_list_projection(record_dict, path):
    """
    Handles the "skills[].name" style path explicitly: extracts a field
    from every item in a list. Kept separate from _resolve_path's general
    walk for clarity, since this is the one genuinely recursive case the
    schema needs (skills[].name -> list of skill name strings).
    """
    m = re.match(r"^([a-zA-Z_]+)\[\]\.(.+)$", path)
    if not m:
        return None, False  # not a list-projection path

    list_key, sub_path = m.group(1), m.group(2)
    items = record_dict.get(list_key)
    if not isinstance(items, list):
        return None, True

    results = []
    for item in items:
        if isinstance(item, dict) and sub_path in item:
            results.append(item[sub_path])
        else:
            results.append(None)
    return results, True


def _apply_normalize(value, normalize_kind):
    if value is None or normalize_kind is None:
        return value

    if normalize_kind == "E.164":
        if isinstance(value, list):
            return [normalize_phone(v) for v in value]
        return normalize_phone(value)

    if normalize_kind == "canonical":
        if isinstance(value, list):
            return [canonicalize_skill(v) if isinstance(v, str) else v for v in value]
        if isinstance(value, str):
            return canonicalize_skill(value)
        return value  # not a string/list-of-strings -> leave structured data untouched

    return value  # unknown normalize kind -> pass through unchanged, never crash


def project(canonical_record, config):
    """
    canonical_record: a CanonicalRecord instance
    config: a validated config dict (see config.py load_config)
    Returns: output dict shaped per config.
    Raises ProjectionError if on_missing == 'error' and a required field is missing.
    """
    full = canonical_record.to_full_dict()
    on_missing = config.get("on_missing", "null")
    output = {}

    for field_spec in config["fields"]:
        path = field_spec["path"]
        source_path = field_spec.get("from", path)
        required = field_spec.get("required", False)
        normalize_kind = field_spec.get("normalize")

        # Try the list-projection form first (e.g. "skills[].name").
        list_result, was_list_projection = _resolve_list_projection(full, source_path)
        if was_list_projection:
            value = list_result
        else:
            value = _resolve_path(full, source_path)

        value = _apply_normalize(value, normalize_kind)

        is_missing = value is None or value == [] or value == ""

        if is_missing:
            if required and on_missing == "error":
                raise ProjectionError(f"Required field '{path}' (from '{source_path}') is missing.")
            if on_missing == "omit":
                continue
            output[path] = None  # on_missing == "null" (default), or non-required field
        else:
            output[path] = value

    if config.get("include_confidence", True):
        output["overall_confidence"] = full["overall_confidence"]

    if config.get("include_provenance", True):
        output["provenance"] = full["provenance"]

    return output
