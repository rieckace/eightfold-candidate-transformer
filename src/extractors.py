"""
Extraction stage: parse each raw source type into a common INTERMEDIATE
shape that the merge stage can consume uniformly, regardless of how
different the raw formats are.

Intermediate shape (per extracted record):
{
    "source": "<source_id>",
    "full_name": str | None,
    "emails": [str],
    "phones": [str],          # raw, not yet normalized
    "location": {"city":..,"region":..,"country":..} | None,
    "links": {"linkedin":.., "github":.., "portfolio":.., "other":[..]},
    "headline": str | None,
    "company": str | None,
    "title": str | None,
    "skills_raw": [str],      # raw skill strings, not yet canonicalized
    "education_raw": [dict],
    "years_experience_hint": float | None,
    "raw_text": str | None,   # only for unstructured/notes sources, used for light NLP-ish extraction
}

Every extractor is wrapped to NEVER raise -- a failing/garbage source
returns None and the pipeline logs + skips it (the "robust" constraint).
"""

import csv
import json
import re
import urllib.request
import urllib.error


def _empty_record(source_id):
    return {
        "source": source_id,
        "full_name": None,
        "emails": [],
        "phones": [],
        "location": None,
        "links": {"linkedin": None, "github": None, "portfolio": None, "other": []},
        "headline": None,
        "company": None,
        "title": None,
        "skills_raw": [],
        "education_raw": [],
        "years_experience_hint": None,
        "raw_text": None,
    }


# ---------------------------------------------------------------------------
# Recruiter CSV extractor
# ---------------------------------------------------------------------------

def extract_recruiter_csv(path, source_id="recruiter_csv"):
    """
    Parses the recruiter CSV export. Each row becomes a separate
    intermediate record (the merge stage handles deduping/matching
    multiple rows for the same person).
    """
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = _empty_record(source_id)
                rec["full_name"] = (row.get("name") or "").strip() or None
                email = (row.get("email") or "").strip()
                if email:
                    rec["emails"] = [email]
                phone = (row.get("phone") or "").strip()
                if phone:
                    rec["phones"] = [phone]
                rec["company"] = (row.get("current_company") or "").strip() or None
                rec["title"] = (row.get("title") or "").strip() or None
                rec["headline"] = (row.get("headline") or "").strip() or None
                if row.get("linkedin") or row.get("github") or row.get("portfolio"):
                    rec["links"] = {
                        "linkedin": (row.get("linkedin") or "").strip() or None,
                        "github": (row.get("github") or "").strip() or None,
                        "portfolio": (row.get("portfolio") or "").strip() or None,
                        "other": [],
                    }
                records.append(rec)
    except (OSError, csv.Error, UnicodeDecodeError):
        return []  # missing/garbage source -> empty list, never crash

    return records


# ---------------------------------------------------------------------------
# ATS JSON extractor
# ---------------------------------------------------------------------------

# Minimal country name -> ISO-3166 alpha-2 lookup for normalization.
_COUNTRY_TO_ISO2 = {
    "taiwan": "TW",
    "india": "IN",
    "nepal": "NP",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
}


def _country_to_iso2(name):
    if not name:
        return None
    return _COUNTRY_TO_ISO2.get(name.strip().lower(), name.strip()[:2].upper())


def extract_ats_json(path, source_id="ats_json"):
    """
    Parses the ATS JSON blob. Field names deliberately do NOT match our
    canonical schema (e.g. 'fullName', 'mobile', 'org') -- this extractor
    is exactly the field-name-remapping layer the assignment calls out.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []  # malformed/missing JSON -> never crash

    if not isinstance(data, dict):
        return []

    cand = data.get("candidate_record")
    if not isinstance(cand, dict):
        return []

    rec = _empty_record(source_id)
    rec["full_name"] = cand.get("fullName") or None

    contact = cand.get("contact") or {}
    if isinstance(contact, dict):
        email = contact.get("primaryEmail")
        if email:
            rec["emails"] = [email]
        mobile = contact.get("mobile")
        if mobile:
            rec["phones"] = [mobile]

    role = cand.get("currentRole") or {}
    if isinstance(role, dict):
        rec["company"] = role.get("org") or None
        rec["title"] = role.get("position") or None
        rec["years_experience_hint"] = role.get("yearsExperience") or rec["years_experience_hint"]

    addr = cand.get("addr") or {}
    if isinstance(addr, dict):
        rec["location"] = {
            "city": addr.get("town"),
            "region": addr.get("state_or_region"),
            "country": _country_to_iso2(addr.get("nation")),
        }

    tags = cand.get("skill_tags")
    if isinstance(tags, list):
        rec["skills_raw"] = [t for t in tags if isinstance(t, str)]

    edu_list = cand.get("edu_history")
    if isinstance(edu_list, list):
        for edu in edu_list:
            if not isinstance(edu, dict):
                continue
            rec["education_raw"].append({
                "institution": edu.get("school"),
                "degree": edu.get("qualification"),
                "field": edu.get("major"),
                "end_year": edu.get("gradYear"),
            })

        # Optional direct profile fields for richer sample inputs.
        rec["headline"] = cand.get("headline") or None
        if isinstance(role, dict):
            start = role.get("start") or role.get("startDate")
            if start:
                rec["start_date"] = start
            summary = role.get("summary")
            if summary:
                rec["summary"] = summary

    return [rec]


# ---------------------------------------------------------------------------
# Recruiter notes (.txt) extractor -- lightweight pattern-based extraction
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")


def extract_recruiter_notes(path, source_id="recruiter_notes"):
    """
    Parses free-text recruiter notes using regex-based extraction for
    emails/phones, and keyword/line scanning for name, location, skills,
    and education. This is intentionally simple pattern matching, not
    full NLP/NER -- a documented scope decision (see README).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return []

    if not text.strip():
        return []

    rec = _empty_record(source_id)
    rec["raw_text"] = text

    # Name: look for "Candidate: <name>" pattern first (common notes convention).
    name_match = re.search(r"Candidate:\s*(.+)", text)
    if name_match:
        rec["full_name"] = name_match.group(1).strip()

    # Emails: take all matches; later merge stage decides which is "preferred"
    # using nearby context cues like "preferred email is X".
    all_emails = _EMAIL_RE.findall(text)
    rec["emails"] = list(dict.fromkeys(all_emails))  # de-dupe, preserve order

    # Preferred-email cue, if present, reorder so preferred is first.
    preferred_match = re.search(r"preferred email is\s+([\w.+-]+@[\w-]+\.[a-zA-Z]{2,})", text, re.IGNORECASE)
    if preferred_match and preferred_match.group(1) in rec["emails"]:
        preferred = preferred_match.group(1)
        rec["emails"].remove(preferred)
        rec["emails"].insert(0, preferred)

    # Phones
    phone_candidates = _PHONE_RE.findall(text)
    cleaned_phones = []
    for p in phone_candidates:
        digits = re.sub(r"\D", "", p)
        if len(digits) >= 8:
            cleaned_phones.append(p.strip())
    rec["phones"] = list(dict.fromkeys(cleaned_phones))

    # Location: look for "based out of <city>, <country/region>" pattern.
    loc_match = re.search(r"based out of\s+([A-Za-z\s]+),\s*([A-Za-z\s]+)", text)
    if loc_match:
        rec["location"] = {
            "city": loc_match.group(1).strip(),
            "region": None,
            "country": _country_to_iso2(loc_match.group(2).strip()),
        }

    # Company / title: look for "<Role> at <Org>" pattern.
    role_match = re.search(r"(?:Working as|working as)\s+(?:an?\s+)?([\w\s]+?)\s+at\s+([\w\s,]+?)(?:\.|,| under| since)", text)
    if role_match:
        rec["title"] = role_match.group(1).strip()
        rec["company"] = role_match.group(2).strip()

    # Skills: look for "Strong in <...>" sentence, then pull every skill-like
    # token from it, including ones tucked inside parentheses, e.g.
    # "Strong in Python, RL/DQN, and has decent full-stack background
    # (React, Node.js, MongoDB)." -- the parenthetical is part of the same
    # sentence and should count as skill signal too.
    skills_sentence_match = re.search(r"Strong in\s+(.+?\))", text)
    if not skills_sentence_match:
        skills_sentence_match = re.search(r"Strong in\s+(.+?)\.", text)
    if skills_sentence_match:
        blob = skills_sentence_match.group(1)
        blob = blob.replace(" and ", ", ").replace("(", ", ").replace(")", "")
        parts = re.split(r",|/", blob)
        for part in parts:
            part = part.strip().strip(".")
            if not part:
                continue
            # Drop obvious non-skill filler phrases.
            if part.lower() in ("has decent full-stack background", "decent full-stack background"):
                continue
            inner = re.findall(r"[\w.+#]+", part)
            for token in inner:
                if token:
                    rec["skills_raw"].append(token)

    # Education: look for degree + institution + expected graduation year.
    edu_match = re.search(
        r"Education mentioned:\s*(.+?),\s*(.+?),\s*expected graduation\s*(\d{4})",
        text,
    )
    if edu_match:
        rec["education_raw"].append({
            "institution": edu_match.group(2).strip(),
            "degree": edu_match.group(1).strip(),
            "field": None,
            "end_year": int(edu_match.group(3)),
        })

    # Years of experience hint, e.g. "around 2 years of overall coding/project experience"
    years_match = re.search(r"(\d+(?:\.\d+)?)\s*years?\s+of\s+(?:overall\s+)?(?:coding|work|project|professional)?", text, re.IGNORECASE)
    if years_match:
        try:
            rec["years_experience_hint"] = float(years_match.group(1))
        except ValueError:
            pass

    return [rec]


# ---------------------------------------------------------------------------
# GitHub profile extractor (bonus unstructured source, live API call)
# ---------------------------------------------------------------------------

def extract_github_profile(username_or_url, source_id="github_profile", timeout=5):
    """
    Calls the public GitHub REST API for a given username (or github.com URL)
    to pull name, bio, public repos (-> used as skill signal via languages),
    and profile link.

    Network-dependent and wrapped defensively: any failure (no network,
    rate limit, 404, timeout) returns an empty list so the pipeline degrades
    gracefully rather than crashing. This is a deliberate demonstration of
    the "robust against missing/garbage source" constraint applied to a
    live external dependency, not just static files.
    """
    username = username_or_url.strip()
    if "github.com" in username:
        username = username.rstrip("/").split("/")[-1]

    if not username:
        return []

    api_url = f"https://api.github.com/users/{username}"
    repos_url = f"https://api.github.com/users/{username}/repos?per_page=100"

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "eightfold-transformer"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            profile = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        return []  # network unavailable / rate-limited / bad username -> degrade gracefully

    rec = _empty_record(source_id)
    rec["full_name"] = profile.get("name") or None
    rec["headline"] = profile.get("bio") or None
    rec["links"]["github"] = profile.get("html_url") or f"https://github.com/{username}"
    blog = profile.get("blog")
    if blog:
        rec["links"]["portfolio"] = blog if blog.startswith("http") else f"https://{blog}"
    loc = profile.get("location")
    if loc:
        rec["location"] = {"city": loc, "region": None, "country": None}

    # Pull languages used across repos as a lightweight skill signal.
    try:
        req2 = urllib.request.Request(repos_url, headers={"User-Agent": "eightfold-transformer"})
        with urllib.request.urlopen(req2, timeout=timeout) as resp2:
            repos = json.loads(resp2.read().decode("utf-8"))
        if isinstance(repos, list):
            langs = {r.get("language") for r in repos if isinstance(r, dict) and r.get("language")}
            rec["skills_raw"] = list(langs)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        pass  # repos fetch failing shouldn't drop the profile data we already have

    return [rec]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

EXTRACTORS = {
    "recruiter_csv": extract_recruiter_csv,
    "ats_json": extract_ats_json,
    "recruiter_notes": extract_recruiter_notes,
    "github_profile": extract_github_profile,
}


def extract(source_type, path_or_identifier, source_id=None):
    """
    Dispatches to the right extractor. Unknown source types or extractor
    exceptions both degrade to an empty list -- this is the single choke
    point that guarantees the 'robust' constraint for every source.
    """
    fn = EXTRACTORS.get(source_type)
    if fn is None:
        return []
    try:
        if source_id:
            return fn(path_or_identifier, source_id=source_id)
        return fn(path_or_identifier)
    except Exception:
        # Final safety net: any unexpected extractor bug must not crash the run.
        return []
