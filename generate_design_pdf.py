"""
Generates the one-page design document PDF for the Eightfold assignment.
Uses reportlab Platypus with compact styles to fit everything on one page.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

OUT_PATH = "/home/claude/eightfold-transformer/Rikesh_Yadav_rikeshyadav2780@gmail.com_Eightfold.pdf"

doc = SimpleDocTemplate(
    OUT_PATH,
    pagesize=letter,
    topMargin=0.45 * inch,
    bottomMargin=0.45 * inch,
    leftMargin=0.55 * inch,
    rightMargin=0.55 * inch,
)

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "TitleCompact", parent=styles["Title"], fontSize=15, leading=18,
    spaceAfter=2, textColor=colors.HexColor("#1a1a2e"),
)
subtitle_style = ParagraphStyle(
    "SubtitleCompact", parent=styles["Normal"], fontSize=9.5, leading=12,
    spaceAfter=8, textColor=colors.HexColor("#555555"),
)
h2_style = ParagraphStyle(
    "H2Compact", parent=styles["Heading2"], fontSize=11, leading=13,
    spaceBefore=7, spaceAfter=3, textColor=colors.HexColor("#16213e"),
)
body_style = ParagraphStyle(
    "BodyCompact", parent=styles["Normal"], fontSize=8.7, leading=11.3,
    spaceAfter=4, alignment=TA_LEFT,
)
mono_style = ParagraphStyle(
    "MonoCompact", parent=styles["Normal"], fontSize=9, leading=12,
    spaceAfter=6, fontName="Courier", textColor=colors.HexColor("#0f3460"),
)
bullet_style = ParagraphStyle(
    "BulletCompact", parent=body_style, leftIndent=12, spaceAfter=3,
    bulletIndent=2,
)

story = []

story.append(Paragraph("Multi-Source Candidate Data Transformer", title_style))
story.append(Paragraph("Technical Design &nbsp;&middot;&nbsp; Rikesh Yadav &nbsp;&middot;&nbsp; rikeshyadav2780@gmail.com", subtitle_style))
story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#cccccc"), spaceAfter=6))

story.append(Paragraph("Pipeline", h2_style))
story.append(Paragraph(
    "<font name='Courier' size='9' color='#0f3460'>detect &rarr; extract &rarr; normalize &rarr; merge &rarr; confidence &rarr; project &rarr; validate</font>",
    body_style
))
story.append(Paragraph(
    "<b>Detect</b> classifies each input (file extension / URL pattern) into a source type. "
    "<b>Extract</b> parses each source's native format into a common intermediate shape &mdash; one function per "
    "source type, each wrapped to never raise, so a broken source degrades to an empty record instead of crashing "
    "the run. <b>Normalize</b> converts phones to E.164, dates to YYYY-MM, and skills to canonical names via an "
    "alias table. <b>Merge</b> clusters intermediate records into one record per real candidate and resolves "
    "conflicts. <b>Confidence</b> scores each field. <b>Project</b> reshapes the canonical record per runtime "
    "config. <b>Validate</b> checks the projected output against the requested schema before returning it. "
    "These are split into independently-testable modules, and the canonical record is never mutated by the "
    "projection layer.",
    body_style
))

story.append(Paragraph("Canonical Schema &amp; Normalized Formats", h2_style))
story.append(Paragraph(
    "Schema follows the assignment's default table exactly (candidate_id, full_name, emails[], phones[], "
    "location, links, headline, years_experience, skills[], experience[], education[], provenance[], "
    "overall_confidence). <b>Phones</b> &rarr; E.164, via a self-contained heuristic normalizer (regex + "
    "configurable default-country fallback) rather than an external dependency, keeping the tool installable "
    "with zero friction. <b>Dates</b> &rarr; YYYY-MM, parsed from a dozen common formats, with \"present\" "
    "preserved literally for ongoing roles. <b>Skills</b> &rarr; canonical display names via an alias map "
    "(\"js\" &rarr; \"JavaScript\", \"RL\" &rarr; \"Reinforcement Learning\"), with unrecognized skills passed "
    "through rather than dropped. <b>Country</b> &rarr; ISO-3166 alpha-2 via lookup (\"Taiwan\" &rarr; \"TW\").",
    body_style
))

story.append(Paragraph("Merge &amp; Conflict-Resolution Policy", h2_style))
story.append(Paragraph(
    "<b>Match key:</b> two records are the same candidate if they share a normalized email or phone &mdash; "
    "name is deliberately not used as a match key (false-positive risk with common names; a documented "
    "trade-off, not an oversight). <b>Trust weights</b> resolve scalar conflicts (full_name, headline, "
    "current role): resume 0.9 &gt; ats_json 0.8 &gt; recruiter_csv 0.75 &gt; linkedin 0.7 &gt; github 0.6 &gt; "
    "recruiter_notes 0.5 &mdash; highest-trust non-null value wins. <b>List fields</b> (emails, phones, skills, "
    "education) are unioned and deduplicated, never silently overwritten. <b>Confidence</b> starts at the "
    "winning source's trust weight, +0.15 (capped at 1.0) if 2+ independent sources agree on the same "
    "normalized value; overall_confidence averages all populated field confidences &mdash; directly encoding "
    "\"honestly-empty beats wrong-but-confident.\"",
    body_style
))

story.append(Paragraph("Runtime Config / Projection", h2_style))
story.append(Paragraph(
    "The internal CanonicalRecord is always full-fidelity. A separate projector reshapes it per a runtime JSON "
    "config: select a field subset, rename via <font name='Courier' size='8'>from</font> (supporting paths like "
    "<font name='Courier' size='8'>emails[0]</font> and list-projections like "
    "<font name='Courier' size='8'>skills[].name</font>), apply per-field normalize (E.164 / canonical), toggle "
    "confidence/provenance, and choose on_missing behavior (null / omit / error). A validation pass then checks "
    "the projected output's shape against the config before it's returned.",
    body_style
))

story.append(Paragraph("Edge Cases Handled", h2_style))
edge_cases = [
    "Same candidate, conflicting data across 3 sources (different email/phone formats, job titles) &mdash; resolved via match-key clustering + trust-weighted selection; covered by automated tests.",
    "Malformed JSON / empty files &mdash; caught at the extractor level, source contributes zero records, run continues without crashing.",
    "Field-name mismatch between source and canonical schema (ATS sample uses fullName/mobile/org/addr.nation) &mdash; the extractor is exactly this remapping layer.",
    "Non-ISO country names (\"Taiwan\" instead of \"TW\") &mdash; converted via lookup at extraction time.",
    "Live external API failure (GitHub source: no network, rate limit, bad username) &mdash; defensive try/except degrades to empty list rather than crashing.",
]
for ec in edge_cases:
    story.append(Paragraph(f"&bull; {ec}", bullet_style))

story.append(Paragraph("Deliberately Descoped (under the 36-hour window)", h2_style))
story.append(Paragraph(
    "LinkedIn and resume (PDF/DOCX) extraction are not implemented &mdash; the extractor interface "
    "(<font name='Courier' size='8'>extract(source_type, path) -&gt; list[dict]</font>) is built so either is a "
    "drop-in addition, not a redesign, but was judged lower-value than hardening the merge/confidence/projection "
    "core given the time constraint. Phone normalization uses a lightweight heuristic, not the full "
    "libphonenumber library, trading perfect international coverage for zero install dependencies. Scale testing "
    "at \"thousands of candidates\" was not performed; the design (no global state, single linear pass, "
    "dict-based clustering) should scale reasonably but wasn't load-tested.",
    body_style
))

doc.build(story)
print(f"PDF generated at {OUT_PATH}")
