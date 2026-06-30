"""
Core data models for the canonical candidate profile.

Design note: We keep a strict separation between the INTERNAL canonical
record (full fidelity, every field always present even if null, full
provenance trail) and the OUTPUT projection (shaped per runtime config).
This file defines only the internal model. See projector.py for the
config-driven reshaping into output JSON.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Provenance:
    field: str          # canonical field path, e.g. "phones[0]" or "full_name"
    source: str         # source identifier, e.g. "recruiter_csv", "github_api", "recruiter_notes"
    method: str         # how the value was derived, e.g. "direct", "regex_extracted", "merged_union", "trust_weighted"

    def to_dict(self):
        return {"field": self.field, "source": self.source, "method": self.method}


@dataclass
class Location:
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2

    def to_dict(self):
        return {"city": self.city, "region": self.region, "country": self.country}


@dataclass
class Links:
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list = field(default_factory=list)

    def to_dict(self):
        return {
            "linkedin": self.linkedin,
            "github": self.github,
            "portfolio": self.portfolio,
            "other": self.other,
        }


@dataclass
class Skill:
    name: str
    confidence: float
    sources: list = field(default_factory=list)  # list of source identifiers

    def to_dict(self):
        return {"name": self.name, "confidence": round(self.confidence, 2), "sources": self.sources}


@dataclass
class Experience:
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None   # YYYY-MM
    end: Optional[str] = None     # YYYY-MM or "present"
    summary: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Education:
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class CanonicalRecord:
    """
    The single internal source of truth for a candidate, after
    detect -> extract -> normalize -> merge -> confidence stages.

    This is intentionally NOT the output shape. The projector.py module
    reshapes this into whatever the runtime config asks for.
    """
    candidate_id: str
    full_name: Optional[str] = None
    emails: list = field(default_factory=list)
    phones: list = field(default_factory=list)
    location: Location = field(default_factory=Location)
    links: Links = field(default_factory=Links)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list = field(default_factory=list)        # list[Skill]
    experience: list = field(default_factory=list)     # list[Experience]
    education: list = field(default_factory=list)      # list[Education]
    provenance: list = field(default_factory=list)     # list[Provenance]
    overall_confidence: float = 0.0

    def add_provenance(self, field_name: str, source: str, method: str):
        self.provenance.append(Provenance(field_name, source, method))

    def to_full_dict(self):
        """Full-fidelity dict matching the default output schema (no projection)."""
        return {
            "candidate_id": self.candidate_id,
            "full_name": self.full_name,
            "emails": self.emails,
            "phones": self.phones,
            "location": self.location.to_dict(),
            "links": self.links.to_dict(),
            "headline": self.headline,
            "years_experience": self.years_experience,
            "skills": [s.to_dict() for s in self.skills],
            "experience": [e.to_dict() for e in self.experience],
            "education": [e.to_dict() for e in self.education],
            "provenance": [p.to_dict() for p in self.provenance],
            "overall_confidence": round(self.overall_confidence, 2),
        }
