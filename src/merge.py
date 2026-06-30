"""
Merge stage: combine intermediate records (possibly several per source,
possibly the same person appearing in multiple sources) into ONE
CanonicalRecord, with full provenance and per-field confidence.

Merge / conflict-resolution policy (documented in design doc too):

1. MATCH KEY: records are considered "the same candidate" if they share
   at least one normalized email OR one normalized phone. (Name alone is
   not used as a match key -- too many false positives from common names.)

2. SOURCE TRUST WEIGHTS (highest wins for single-value fields):
     resume          : 0.9   (most authoritative, candidate-authored)
     ats_json        : 0.8   (structured, employer-validated)
     recruiter_csv    : 0.75  (structured, but lower-fidelity columns)
     linkedin_profile : 0.7
     github_profile   : 0.6   (good for skills, weak for personal info)
     recruiter_notes  : 0.5   (free text, human-paraphrased, most error-prone)
   These are configurable (see config.py DEFAULT_TRUST_WEIGHTS).

3. SCALAR FIELDS (full_name, headline, company/title used for latest
   experience entry): pick the value from the highest-trust source that
   provided a non-null value. Ties broken by first-seen order.

4. LIST FIELDS (emails, phones, skills, education): UNION + dedupe
   (after normalization), never silently drop a value a human source
   actually gave us.

5. CONFIDENCE PER FIELD: 
     base = trust_weight of the winning source
     + agreement_bonus: +0.15 if >=2 sources agree on the same
       (normalized) value, capped at 1.0
   overall_confidence = average of all populated field confidences.

6. PROVENANCE: every populated field gets at least one Provenance entry
   tagging which source(s) contributed it and how (direct / merged_union /
   trust_weighted / regex_extracted).
"""

from models import CanonicalRecord, Location, Links, Skill, Experience, Education
from normalize import normalize_phone, normalize_date, canonicalize_skill


DEFAULT_TRUST_WEIGHTS = {
    "resume": 0.9,
    "ats_json": 0.8,
    "recruiter_csv": 0.75,
    "linkedin_profile": 0.7,
    "github_profile": 0.6,
    "recruiter_notes": 0.5,
}


def _trust(source, weights):
    return weights.get(source, 0.4)  # unknown sources get a conservative low weight


def _group_by_candidate(all_records):
    """
    Groups intermediate records into candidate clusters using shared
    normalized email or phone as the match key. Records that share no
    identifying info with any existing cluster start a new cluster --
    this is a deliberate, documented simplification (no fuzzy name
    matching) to keep matching deterministic and explainable.
    """
    clusters = []  # list of lists of records

    def normalized_keys(rec):
        keys = set()
        for e in rec.get("emails", []):
            if e:
                keys.add(("email", e.strip().lower()))
        for p in rec.get("phones", []):
            np = normalize_phone(p)
            if np:
                keys.add(("phone", np))
        return keys

    for rec in all_records:
        rec_keys = normalized_keys(rec)
        matched_cluster = None
        for cluster in clusters:
            cluster_keys = set()
            for r in cluster:
                cluster_keys |= normalized_keys(r)
            if rec_keys & cluster_keys:
                matched_cluster = cluster
                break
        if matched_cluster is not None:
            matched_cluster.append(rec)
        else:
            clusters.append([rec])

    return clusters


def _pick_scalar(records, field_name, weights):
    """
    Picks the value of a scalar field from the highest-trust source that
    has a non-null value. Returns (value, winning_source, agreement_count).
    """
    candidates = []  # (trust, source, value)
    for r in records:
        val = r.get(field_name)
        if val:
            candidates.append((_trust(r["source"], weights), r["source"], val))

    if not candidates:
        return None, None, 0

    candidates.sort(key=lambda c: c[0], reverse=True)
    winner_value = candidates[0][2]
    winner_source = candidates[0][1]

    agreement = sum(1 for c in candidates if str(c[2]).strip().lower() == str(winner_value).strip().lower())
    return winner_value, winner_source, agreement


def _confidence(base_trust, agreement_count):
    bonus = 0.15 if agreement_count >= 2 else 0.0
    return min(1.0, base_trust + bonus)


def merge_records(all_records, trust_weights=None):
    """
    Takes the flat list of intermediate records from ALL sources (already
    extracted), groups them by candidate, and returns a list of
    CanonicalRecord (normally just one, for a single-candidate run, but
    the design supports batch/multi-candidate naturally).
    """
    weights = trust_weights or DEFAULT_TRUST_WEIGHTS
    clusters = _group_by_candidate(all_records)
    canonical_records = []

    for idx, cluster in enumerate(clusters):
        candidate_id = f"cand_{idx+1:04d}"
        rec = CanonicalRecord(candidate_id=candidate_id)

        # --- full_name ---
        name_val, name_src, name_agree = _pick_scalar(cluster, "full_name", weights)
        if name_val:
            rec.full_name = name_val
            rec.add_provenance("full_name", name_src, "trust_weighted")

        # --- emails: union + dedupe, preferred-first if any source flagged one ---
        seen_emails = []
        email_sources = {}
        for r in cluster:
            for e in r.get("emails", []):
                key = e.strip().lower()
                if key not in [x.lower() for x in seen_emails]:
                    seen_emails.append(e.strip())
                    email_sources[e.strip()] = r["source"]
        rec.emails = seen_emails
        for e in seen_emails:
            rec.add_provenance(f"emails[{seen_emails.index(e)}]", email_sources[e], "merged_union")

        # --- phones: normalize, union + dedupe on normalized value ---
        seen_phones = []
        phone_sources = {}
        for r in cluster:
            for p in r.get("phones", []):
                np = normalize_phone(p)
                if np and np not in seen_phones:
                    seen_phones.append(np)
                    phone_sources[np] = r["source"]
        rec.phones = seen_phones
        for p in seen_phones:
            rec.add_provenance(f"phones[{seen_phones.index(p)}]", phone_sources[p], "merged_union+normalized")

        # --- location: pick from highest-trust source with a non-null location ---
        loc_candidates = [(_trust(r["source"], weights), r["source"], r["location"])
                           for r in cluster if r.get("location")]
        if loc_candidates:
            loc_candidates.sort(key=lambda c: c[0], reverse=True)
            _, loc_src, loc_val = loc_candidates[0]
            rec.location = Location(
                city=loc_val.get("city"),
                region=loc_val.get("region"),
                country=loc_val.get("country"),
            )
            rec.add_provenance("location", loc_src, "trust_weighted")

        # --- links ---
        for r in cluster:
            links = r.get("links") or {}
            if links.get("github") and not rec.links.github:
                rec.links.github = links["github"]
                rec.add_provenance("links.github", r["source"], "direct")
            if links.get("linkedin") and not rec.links.linkedin:
                rec.links.linkedin = links["linkedin"]
                rec.add_provenance("links.linkedin", r["source"], "direct")
            if links.get("portfolio") and not rec.links.portfolio:
                rec.links.portfolio = links["portfolio"]
                rec.add_provenance("links.portfolio", r["source"], "direct")
            for other in links.get("other", []):
                if other not in rec.links.other:
                    rec.links.other.append(other)

        # --- headline ---
        headline_val, headline_src, _ = _pick_scalar(cluster, "headline", weights)
        if headline_val:
            rec.headline = headline_val
            rec.add_provenance("headline", headline_src, "trust_weighted")

        # --- years_experience: take the max hint across sources (conservative-low sources still count) ---
        year_hints = [(r["source"], r.get("years_experience_hint")) for r in cluster if r.get("years_experience_hint") is not None]
        if year_hints:
            year_hints.sort(key=lambda c: c[1], reverse=True)
            rec.years_experience = year_hints[0][1]
            rec.add_provenance("years_experience", year_hints[0][0], "regex_extracted")

        # --- skills: canonicalize + union, confidence boosted by cross-source agreement ---
        skill_sources = {}  # canonical_name -> set(sources)
        for r in cluster:
            for raw_skill in r.get("skills_raw", []):
                canon = canonicalize_skill(raw_skill)
                if not canon:
                    continue
                skill_sources.setdefault(canon, set()).add(r["source"])

        for name, sources in sorted(skill_sources.items()):
            base_trust = max(_trust(s, weights) for s in sources)
            conf = _confidence(base_trust, len(sources))
            rec.skills.append(Skill(name=name, confidence=conf, sources=sorted(sources)))
        if rec.skills:
            rec.add_provenance("skills", "+".join(sorted({s for sl in skill_sources.values() for s in sl})), "merged_union+canonicalized")

        # --- experience: build one entry per cluster from company/title (current role),
        # using the highest-trust source's pairing to avoid mixing mismatched company/title
        # from different sources. ---
        exp_candidates = [(_trust(r["source"], weights), r["source"], r.get("company"), r.get("title"))
                           for r in cluster if r.get("company") or r.get("title")]
        if exp_candidates:
            exp_candidates.sort(key=lambda c: c[0], reverse=True)
            _, exp_src, company, title = exp_candidates[0]
            rec.experience.append(Experience(company=company, title=title, start=None, end="present", summary=None))
            rec.add_provenance("experience[0]", exp_src, "trust_weighted")

        # --- education: dedupe by institution (degree wording often varies
        # across sources for the same actual degree, e.g. "B.E." vs
        # "B.E/B.Tech" -- matching on institution alone and keeping the
        # highest-trust source's version avoids spurious duplicate entries) ---
        edu_by_institution = {}  # institution -> (trust, source, edu_dict)
        for r in cluster:
            for edu in r.get("education_raw", []):
                inst = edu.get("institution")
                if not inst:
                    continue
                t = _trust(r["source"], weights)
                existing = edu_by_institution.get(inst)
                if existing is None or t > existing[0]:
                    edu_by_institution[inst] = (t, r["source"], edu)

        for inst, (trust_val, src, edu) in edu_by_institution.items():
            rec.education.append(Education(
                institution=edu.get("institution"),
                degree=edu.get("degree"),
                field=edu.get("field"),
                end_year=edu.get("end_year"),
            ))
            rec.add_provenance(f"education[{len(rec.education)-1}]", src, "trust_weighted")

        # --- overall_confidence: average of populated field-level confidences ---
        field_confidences = []
        if name_val:
            field_confidences.append(_confidence(_trust(name_src, weights), name_agree))
        if rec.phones:
            field_confidences.append(0.85)  # normalization succeeded = high confidence
        if rec.emails:
            field_confidences.append(0.8)
        for sk in rec.skills:
            field_confidences.append(sk.confidence)

        rec.overall_confidence = sum(field_confidences) / len(field_confidences) if field_confidences else 0.0

        canonical_records.append(rec)

    return canonical_records
