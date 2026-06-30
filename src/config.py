"""
Runtime config handling for the projection layer.

Config shape (matches the assignment's example):
{
  "fields": [
    {"path": "full_name", "type": "string", "required": true},
    {"path": "primary_email", "from": "emails[0]", "type": "string", "required": true},
    {"path": "phone", "from": "phones[0]", "type": "string", "normalize": "E.164"},
    {"path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical"}
  ],
  "include_confidence": true,
  "include_provenance": true,
  "on_missing": "null" | "omit" | "error"
}

Design note: this config module ONLY validates shape and supplies
defaults. The actual reshaping logic lives in projector.py, keeping a
clean separation between "what was asked for" (config) and "how we
produce it" (projector).
"""

DEFAULT_CONFIG = {
    "fields": [
        {"path": "candidate_id", "type": "string", "required": True},
        {"path": "full_name", "type": "string", "required": False},
        {"path": "emails", "type": "string[]", "required": False},
        {"path": "phones", "type": "string[]", "required": False, "normalize": "E.164"},
        {"path": "location", "type": "object", "required": False},
        {"path": "links", "type": "object", "required": False},
        {"path": "headline", "type": "string", "required": False},
        {"path": "years_experience", "type": "number", "required": False},
        {"path": "skills", "type": "array", "required": False},
        {"path": "experience", "type": "array", "required": False},
        {"path": "education", "type": "array", "required": False},
    ],
    "include_confidence": True,
    "include_provenance": True,
    "on_missing": "null",
}

VALID_ON_MISSING = {"null", "omit", "error"}
VALID_TYPES = {"string", "number", "boolean", "object", "array", "string[]", "number[]"}


class ConfigError(Exception):
    """Raised when a runtime config is structurally invalid."""
    pass


def load_config(config_dict=None):
    """
    Merges a user-supplied config with sane defaults and validates shape.
    Passing None returns the DEFAULT_CONFIG (full schema, default behavior).
    Raises ConfigError on structurally invalid configs (never silently
    accepts garbage config -- this is itself a "garbage input" case, but
    for *config*, failing loudly is the correct behavior since this is
    operator input, not candidate data).
    """
    if config_dict is None:
        return dict(DEFAULT_CONFIG)

    if not isinstance(config_dict, dict):
        raise ConfigError("Config must be a JSON object.")

    fields = config_dict.get("fields")
    if not isinstance(fields, list) or len(fields) == 0:
        raise ConfigError("Config must include a non-empty 'fields' array.")

    for f in fields:
        if not isinstance(f, dict):
            raise ConfigError(f"Each field entry must be an object, got: {f!r}")
        if "path" not in f:
            raise ConfigError(f"Field entry missing required 'path': {f!r}")
        if "type" in f and f["type"] not in VALID_TYPES:
            raise ConfigError(f"Invalid type '{f['type']}' for field '{f['path']}'.")

    on_missing = config_dict.get("on_missing", "null")
    if on_missing not in VALID_ON_MISSING:
        raise ConfigError(f"Invalid on_missing value: {on_missing!r}. Must be one of {VALID_ON_MISSING}.")

    merged = {
        "fields": fields,
        "include_confidence": config_dict.get("include_confidence", True),
        "include_provenance": config_dict.get("include_provenance", True),
        "on_missing": on_missing,
    }
    return merged
