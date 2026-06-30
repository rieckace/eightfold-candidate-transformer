"""
Normalization functions: phone -> E.164, dates -> YYYY-MM, skills -> canonical names.

Design note: we deliberately avoid heavy external dependencies (e.g. the
`phonenumbers` library) so this tool runs anywhere with zero install
friction. Phone normalization here is heuristic-based (regex + a default
country fallback), not a full libphonenumber-grade implementation. This
is a documented, deliberate scope trade-off (see README "Assumptions").
"""

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Phone normalization -> E.164  (+<countrycode><number>, no spaces/dashes)
# ---------------------------------------------------------------------------

# Minimal country-code table for common cases we expect in sample data.
# Extend as needed; unknown/ambiguous numbers fall back to DEFAULT_COUNTRY.
_COUNTRY_CALLING_CODES = {
    "IN": "91",
    "US": "1",
    "TW": "886",
    "NP": "977",
    "GB": "44",
}

DEFAULT_COUNTRY = "IN"  # configurable fallback used when a number has no explicit country code


def normalize_phone(raw: str, default_country: str = DEFAULT_COUNTRY):
    """
    Normalize a raw phone string to E.164 format: +<countrycode><digits>.
    Returns None if the input is garbage / unparseable (never invents data).
    """
    if not raw or not isinstance(raw, str):
        return None

    digits = re.sub(r"[^\d+]", "", raw.strip())
    if not digits:
        return None

    if digits.startswith("+"):
        # Already has an explicit country code marker.
        candidate = digits
    elif digits.startswith("00"):
        # International prefix written as 00 instead of +.
        candidate = "+" + digits[2:]
    else:
        # No country code present -> apply default country's calling code.
        cc = _COUNTRY_CALLING_CODES.get(default_country, "91")
        # Strip a leading 0 (common trunk prefix) before prepending the code.
        local = digits.lstrip("0")
        candidate = f"+{cc}{local}"

    # Sanity check: E.164 numbers are 8-15 digits after the '+'.
    digits_only = candidate[1:]
    if not digits_only.isdigit() or not (8 <= len(digits_only) <= 15):
        return None

    return candidate


# ---------------------------------------------------------------------------
# Date normalization -> YYYY-MM
# ---------------------------------------------------------------------------

_MONTH_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m",
    "%b %Y", "%B %Y", "%m/%Y", "%m-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
]


def normalize_date(raw):
    """
    Normalize a wide variety of date string formats to 'YYYY-MM'.
    Returns the literal string 'present' for ongoing roles.
    Returns None if unparseable (never guesses).
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    if text.lower() in ("present", "current", "now", "ongoing"):
        return "present"

    for fmt in _MONTH_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return f"{dt.year:04d}-{dt.month:02d}"
        except ValueError:
            continue

    # Bare year, e.g. "2021" -> treat as January of that year (low-confidence;
    # caller should weight this lower in confidence scoring if needed).
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-01"

    return None


# ---------------------------------------------------------------------------
# Skill canonicalization
# ---------------------------------------------------------------------------

# Alias map: lowercase variant -> canonical display name.
# This is intentionally a small, extensible seed set, not an exhaustive taxonomy.
_SKILL_ALIASES = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "py": "Python",
    "python": "Python",
    "py3": "Python",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "express": "Express.js",
    "expressjs": "Express.js",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "ai": "Artificial Intelligence",
    "dl": "Deep Learning",
    "deep learning": "Deep Learning",
    "rl": "Reinforcement Learning",
    "reinforcement learning": "Reinforcement Learning",
    "dqn": "Deep Q-Networks",
    "java": "Java",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "golang": "Go",
    "go": "Go",
    "sql": "SQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "docker": "Docker",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "git": "Git",
    "github": "GitHub",
    "html": "HTML",
    "css": "CSS",
    "rest api": "REST APIs",
    "rest": "REST APIs",
    "graphql": "GraphQL",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "pandas": "Pandas",
    "numpy": "NumPy",
}


def canonicalize_skill(raw: str):
    """
    Map a raw skill string to its canonical display name.
    Falls back to a title-cased version of the input if no alias is found
    (never drops a skill it doesn't recognize -- robustness over precision).
    """
    if not raw or not isinstance(raw, str):
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return _SKILL_ALIASES.get(key, raw.strip())
