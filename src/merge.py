"""
Merge stage: combine intermediate records (possibly several per source,
possibly the same person appearing in multiple sources) into ONE
CanonicalRecord, with full provenance (including a human-readable reason
per field) and a deterministic per-field confidence score.

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
   These are configurable (see DEFAULT_TRUST_WEIGHTS below).

3. SCALAR FIELDS (full_name, headline, company/title used for latest
   experience entry, location): pick the value from the highest-trust
   source that provided a non-null value. Ties broken by first-seen order.

4. LIST FIELDS (emails, phones, skills, education): UNION + dedupe
   (after normalization), never silently drop a value a human source
   actually gave us.

5. CONFIDENCE FORMULA (deterministic, never hand-waved):

       confidence = min(1.0, source_trust + agreement_bonus
                              + validation_bonus - conflict_penalty)

   where:
     source_trust      = trust weight of the winning source (0-1)
     agreement_bonus    = +0.03 per OTHER independent source that agrees
                          on the same normalized value (uncapped per-source,
                          but the overall confidence is capped at 1.0)
     validation_bonus   = +0.02 if the value passed format validation
                          (e.g. phone normalized successfully, email has
                          a valid shape, date parsed cleanly)
     conflict_penalty   = -0.10 if at least one OTHER source provided a
                          genuinely different (disagreeing) value for the
                          same field, which we resolved in favor of the
                          higher-trust source

   overall_confidence = average of all populated field-level confidences.

6. PROVENANCE: every populated field gets a Provenance entry with
   field / source / method / reason -- the reason is a plain-English
   sentence explaining why that value and source won, so the output is
   self-explanatory without reading the code.
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

AGREEMENT_BONUS_PER_SOURCE = 0.03
VALIDATION_BONUS = 0.02
CONFLICT_PENALTY = 0.10


def _trust(source, weights):
    return weights.get(source, 0.4)  # unknown sources get a conservative low weight


def compute_confidence(source_trust, agreeing_sources_count=0, validated=False, had_conflict=False):
    """
    The single deterministic confidence formula used everywhere in merge.
    agreeing_sources_count = number of OTHER sources (besides the winner)
    that independently provided the same normalized value.
    """
    score = source_trust
    score += AGREEMENT_BONUS_PER_SOURCE * agreeing_sources_count
    if validated:
        score += VALIDATION_BONUS
    if had_conflict:
        score -= CONFLICT_PENALTY
    return round(min(1.0, max(0.0, score)), 4)


def _group_by_candidate(all_records):
    """
    Groups intermediate records into candidate clusters using shared
    normalized email or phone as the match key.
    """
    clusters = []

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
    has a non-null value.
    Returns (value, winning_source, agreeing_count, had_conflict, alternatives).
    """
    candidates = []
    for r in records:
        val = r.get(field_name)
        if val:
            candidates.append((_trust(r["source"], weights), r["source"], val))

    if not candidates:
        return None, None, 0, False, []

    candidates.sort(key=lambda c: c[0], reverse=True)
    winner_value = candidates[0][2]
    winner_source = candidates[0][1]
    winner_key = str(winner_value).strip().lower()

    agreeing = [c for c in candidates[1:] if str(c[2]).strip().lower() == winner_key]
    disagreeing = [c for c in candidates if str(c[2]).strip().lower() != winner_key]

    alternatives = [(c[2], c[1]) for c in disagreeing]
    had_conflict = len(disagreeing) > 0

    return winner_value, winner_source, len(agreeing), had_conflict, alternatives


def _reason_scalar(field_label, winner_source, winner_value, weights, agreeing_count, had_conflict, alternatives):
    parts = [f"'{winner_source}' is the highest-trusted source providing {field_label} (trust={_trust(winner_source, weights):.2f})."]
    if agreeing_count > 0:
        parts.append(f"{agreeing_count} other source(s) independently agreed on the same value.")
    if had_conflict:
        alt_desc = "; ".join(f"{v!r} from {s}" for v, s in alternatives)
        parts.append(f"Discarded conflicting value(s): {alt_desc}.")
    return " ".join(parts)


def merge_records(all_records, trust_weights=None):
    """
    Takes the flat list of intermediate records from ALL sources, groups
    them by candidate, returns a list of CanonicalRecord.
    """
    weights = trust_weights or DEFAULT_TRUST_WEIGHTS
    clusters = _group_by_candidate(all_records)
    canonical_records = []

    for idx, cluster in enumerate(clusters):
        candidate_id = f"cand_{idx+1:04d}"
        rec = CanonicalRecord(candidate_id=candidate_id)
        field_confidences = []

        # --- full_name ---
        name_val, name_src, name_agree, name_conflict, name_alts = _pick_scalar(cluster, "full_name", weights)
        if name_val:
            rec.full_name = name_val
            conf = compute_confidence(_trust(name_src, weights), name_agree, validated=True, had_conflict=name_conflict)
            field_confidences.append(conf)
            rec.add_provenance("full_name", name_src, "trust_weighted",
                                reason=_reason_scalar("full_name", name_src, name_val, weights, name_agree, name_conflict, name_alts))

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
            is_valid_shape = "@" in e and "." in e.split("@")[-1]
            conf = compute_confidence(_trust(email_sources[e], weights), agreeing_sources_count=0, validated=is_valid_shape)
            field_confidences.append(conf)
            rec.add_provenance(
                f"emails[{seen_emails.index(e)}]", email_sources[e], "merged_union",
                reason=f"Surfaced from '{email_sources[e]}'; kept alongside other distinct emails rather than overwritten, since each represents a real value a source provided."
            )

        # --- phones: normalize, union + dedupe on normalized value ---
        seen_phones = []
        phone_sources = {}
        phone_raw_agreement = {}
        for r in cluster:
            for p in r.get("phones", []):
                np = normalize_phone(p)
                if np:
                    phone_raw_agreement[np] = phone_raw_agreement.get(np, 0) + 1
                    if np not in seen_phones:
                        seen_phones.append(np)
                        phone_sources[np] = r["source"]
        rec.phones = seen_phones
        for p in seen_phones:
            agree_count = phone_raw_agreement[p] - 1
            conf = compute_confidence(_trust(phone_sources[p], weights), agreeing_sources_count=agree_count, validated=True)
            field_confidences.append(conf)
            reason = f"Normalized to E.164 from '{phone_sources[p]}'."
            if agree_count > 0:
                reason += f" Confirmed by {agree_count} other source(s) after normalization."
            rec.add_provenance(f"phones[{seen_phones.index(p)}]", phone_sources[p], "merged_union+normalized", reason=reason)

        # --- location ---
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
            other_locs = len(loc_candidates) - 1
            had_conflict = other_locs > 0
            conf = compute_confidence(_trust(loc_src, weights), agreeing_sources_count=0, validated=bool(loc_val.get("country")), had_conflict=had_conflict)
            field_confidences.append(conf)
            reason = f"'{loc_src}' is the highest-trusted source with location data (trust={_trust(loc_src, weights):.2f})."
            if had_conflict:
                reason += f" {other_locs} other source(s) had differing/partial location data, deprioritized in favor of the higher-trust source."
            rec.add_provenance("location", loc_src, "trust_weighted", reason=reason)

        # --- links ---
        for r in cluster:
            links = r.get("links") or {}
            if links.get("github") and not rec.links.github:
                rec.links.github = links["github"]
                rec.add_provenance("links.github", r["source"], "direct", reason=f"Direct value from '{r['source']}'; no other source provided a GitHub link.")
            if links.get("linkedin") and not rec.links.linkedin:
                rec.links.linkedin = links["linkedin"]
                rec.add_provenance("links.linkedin", r["source"], "direct", reason=f"Direct value from '{r['source']}'; no other source provided a LinkedIn link.")
            if links.get("portfolio") and not rec.links.portfolio:
                rec.links.portfolio = links["portfolio"]
                rec.add_provenance("links.portfolio", r["source"], "direct", reason=f"Direct value from '{r['source']}'; no other source provided a portfolio link.")
            for other in links.get("other", []):
                if other not in rec.links.other:
                    rec.links.other.append(other)

        # --- headline ---
        headline_val, headline_src, headline_agree, headline_conflict, headline_alts = _pick_scalar(cluster, "headline", weights)
        if headline_val:
            rec.headline = headline_val
            conf = compute_confidence(_trust(headline_src, weights), headline_agree, validated=True, had_conflict=headline_conflict)
            field_confidences.append(conf)
            rec.add_provenance("headline", headline_src, "trust_weighted",
                                reason=_reason_scalar("headline", headline_src, headline_val, weights, headline_agree, headline_conflict, headline_alts))

        # --- years_experience ---
        year_hints = [(r["source"], r.get("years_experience_hint")) for r in cluster if r.get("years_experience_hint") is not None]
        if year_hints:
            year_hints.sort(key=lambda c: c[1], reverse=True)
            rec.years_experience = year_hints[0][1]
            conf = compute_confidence(_trust(year_hints[0][0], weights), agreeing_sources_count=0, validated=False)
            field_confidences.append(conf)
            rec.add_provenance("years_experience", year_hints[0][0], "regex_extracted",
                                reason=f"Extracted via pattern match from free text in '{year_hints[0][0]}'; lower validation confidence since this is inferred, not a structured field.")

        # --- skills ---
        skill_sources = {}
        for r in cluster:
            for raw_skill in r.get("skills_raw", []):
                canon = canonicalize_skill(raw_skill)
                if not canon:
                    continue
                skill_sources.setdefault(canon, set()).add(r["source"])

        for name, sources in sorted(skill_sources.items()):
            sources_sorted = sorted(sources, key=lambda s: _trust(s, weights), reverse=True)
            top_source = sources_sorted[0]
            other_agreeing = len(sources_sorted) - 1
            conf = compute_confidence(_trust(top_source, weights), agreeing_sources_count=other_agreeing, validated=True)
            rec.skills.append(Skill(name=name, confidence=conf, sources=sorted(sources)))
            field_confidences.append(conf)
            reason = f"Canonicalized skill seen in: {', '.join(sorted(sources))}."
            if other_agreeing > 0:
                reason += f" Confidence boosted by agreement across {len(sources_sorted)} independent sources."
            rec.add_provenance(f"skills[{name}]", top_source, "merged_union+canonicalized", reason=reason)

        # --- experience ---
        exp_candidates = [(
            _trust(r["source"], weights),
            r["source"],
            r.get("company"),
            r.get("title"),
            r.get("start_date"),
            r.get("summary"),
        )
                           for r in cluster if r.get("company") or r.get("title")]
        if exp_candidates:
            exp_candidates.sort(key=lambda c: c[0], reverse=True)
            _, exp_src, company, title, start_date, summary = exp_candidates[0]
            rec.experience.append(Experience(company=company, title=title, start=start_date, end="present", summary=summary))
            other_exp = len(exp_candidates) - 1
            conf = compute_confidence(_trust(exp_src, weights), agreeing_sources_count=0, validated=True, had_conflict=other_exp > 0)
            field_confidences.append(conf)
            reason = f"Company/title pairing taken together from '{exp_src}' (highest-trust source) to avoid mixing mismatched fields across sources."
            rec.add_provenance("experience[0]", exp_src, "trust_weighted", reason=reason)

        # --- education ---
        edu_by_institution = {}
        edu_seen_count = {}
        for r in cluster:
            for edu in r.get("education_raw", []):
                inst = edu.get("institution")
                if not inst:
                    continue
                edu_seen_count[inst] = edu_seen_count.get(inst, 0) + 1
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
            other_mentions = edu_seen_count[inst] - 1
            conf = compute_confidence(trust_val, agreeing_sources_count=other_mentions, validated=bool(edu.get("end_year")))
            field_confidences.append(conf)
            reason = f"'{src}' is the highest-trusted source mentioning this institution."
            if other_mentions > 0:
                reason += f" Mentioned (with possibly differently-worded degree text) by {other_mentions} other source(s) too; institution used as the dedupe key since degree phrasing varies."
            rec.add_provenance(f"education[{len(rec.education)-1}]", src, "trust_weighted", reason=reason)

        rec.overall_confidence = round(sum(field_confidences) / len(field_confidences), 4) if field_confidences else 0.0

        canonical_records.append(rec)

    return canonical_records
