"""
Validation stage: after projection, verify the output actually matches
what the config asked for (right fields present, right shapes) before
returning it. This is the last gate before output -- catches projector
bugs or config/data mismatches rather than silently shipping bad JSON.
"""

class ValidationError(Exception):
    pass


_TYPE_CHECKERS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string[]": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v if x is not None),
    "number[]": lambda v: isinstance(v, list) and all(isinstance(x, (int, float)) for x in v if x is not None),
}


def validate_output(output, config):
    """
    Checks that every field the config declared (and wasn't omitted by
    on_missing='omit') is present with a type-compatible value, and that
    required fields are non-null. Returns (is_valid, list_of_error_strings)
    rather than raising, so the CLI can decide how to surface problems.
    """
    errors = []
    on_missing = config.get("on_missing", "null")

    for field_spec in config["fields"]:
        path = field_spec["path"]
        required = field_spec.get("required", False)
        declared_type = field_spec.get("type")

        if path not in output:
            if on_missing == "omit":
                continue  # expected to be absent, not an error
            errors.append(f"Expected field '{path}' is missing from output entirely.")
            continue

        value = output[path]

        if value is None:
            if required:
                errors.append(f"Required field '{path}' is null in output.")
            continue  # null is acceptable for non-required fields under on_missing='null'

        if declared_type and declared_type in _TYPE_CHECKERS:
            if not _TYPE_CHECKERS[declared_type](value):
                errors.append(f"Field '{path}' expected type '{declared_type}' but got value of type {type(value).__name__}.")

    is_valid = len(errors) == 0
    return is_valid, errors
