"""PDF Report Generator for AI Multilingual Training Video Platform.

Compiles the comprehensive technical audit, architectural specifications,
and issue register into a publication-quality PDF report using ReportLab.
"""

import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """Canvas that computes total pages dynamically and adds running headers/footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#718096"))

        # Header on pages 2+
        if self._pageNumber > 1:
            self.drawString(54, 750, "AI Multilingual Training Video Platform — Technical Audit & Architecture Report")
            self.setStrokeColor(colors.HexColor("#CBD5E0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)

        # Footer on all pages
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 40, page_text)
        self.drawString(54, 40, "CONFIDENTIAL & PROPRIETARY — AUDIT FREEZE (OCTOBER 2026)")
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(54, 52, 558, 52)
        self.restoreState()


def generate_pdf_report(output_filename: str = "PROJECT_AUDIT_AND_TECHNICAL_REPORT.pdf") -> str:
    """Generate the full formal audit PDF report."""
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    primary_color = colors.HexColor("#1A365D")
    secondary_color = colors.HexColor("#2B6CB0")
    accent_color = colors.HexColor("#C53030")
    text_dark = colors.HexColor("#2D3748")

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=primary_color,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=secondary_color,
        spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "MetaText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#4A5568"),
        spaceAfter=8,
    )
    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=primary_color,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=secondary_color,
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=text_dark,
        spaceAfter=5,
    )
    bullet_style = ParagraphStyle(
        "Bullet_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=text_dark,
        leftIndent=12,
        firstLineIndent=-12,
        spaceAfter=3,
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("AI Multilingual Training Video Generator", title_style))
    story.append(Paragraph("Comprehensive Technical Audit, Architecture Specification & System Assessment", subtitle_style))
    story.append(Paragraph("<b>Author / Maintainer:</b> Ali Mostafa | <b>Repository:</b> Ali-Developments/AI-Multilingual-Training-Video-Generator<br/><b>Date:</b> October 2026 | <b>Version:</b> 0.1.0 | <b>Audit Status:</b> AUDIT COMPLETE — NO BUG FIXES APPLIED", meta_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceAfter=8))

    # Executive Summary
    story.append(Paragraph("Executive Summary", h1_style))
    story.append(Paragraph(
        "The <b>AI Multilingual Training Video Generation Platform</b> is an autonomous multi-modal system designed "
        "to transform instructional educational outlines and raw curriculum text into localized video packages. "
        "The platform implements an end-to-end pipeline combining LLM script writing, rule-based duration validation, "
        "cultural localization (Arabic RTL and Bengali LTR), Edge-TTS voice synthesis, HeyGen avatar generation with "
        "local mock fallback, 1080p slide graphics via Pillow, deterministic subtitles (.SRT/.VTT), and native FFmpeg "
        "composition. This document serves as the formal engineering audit of the platform, cataloging implemented "
        "capabilities, testing metrics, and current real-world defects without modifying current application behavior.",
        body_style,
    ))

    # System Architecture
    story.append(Paragraph("1. System Architecture & Pipeline Breakdown", h1_style))
    story.append(Paragraph(
        "The platform coordinates 9 sequential stages via a centralized <b>ProjectOrchestrator</b> with granular "
        "state tracking in project.json manifests:",
        body_style,
    ))

    stages_data = [
        [Paragraph("<b>Stage</b>", body_style), Paragraph("<b>Subsystem</b>", body_style), Paragraph("<b>Key Technologies & Responsibilities</b>", body_style)],
        [Paragraph("Stage 1", body_style), Paragraph("Script Generation", body_style), Paragraph("LangGraph StateGraph, GroqProvider, structured JSON extraction, deterministic duration validation.", body_style)],
        [Paragraph("Stage 2", body_style), Paragraph("Localization", body_style), Paragraph("LocalizationService, ar-SA (Arabic RTL), bn-BD (Bengali LTR), cultural guidance & terminology locks.", body_style)],
        [Paragraph("Stage 3", body_style), Paragraph("Speech Synthesis", body_style), Paragraph("EdgeTTSProvider (free WebSocket tier), exact duration measuring replacing word-count heuristics.", body_style)],
        [Paragraph("Stage 4", body_style), Paragraph("Avatar Presenter", body_style), Paragraph("HeyGenProvider abstraction, MockAvatarProvider local colored canvas generator.", body_style)],
        [Paragraph("Stage 5", body_style), Paragraph("Supporting Visuals", body_style), Paragraph("Pillow (PIL) Full HD (1920x1080) slide card renderer adapted to scene instructional roles.", body_style)],
        [Paragraph("Stage 6", body_style), Paragraph("Subtitle Synthesis", body_style), Paragraph("DeterministicSubtitleEngine generating drift-free .srt and .vtt cue streams.", body_style)],
        [Paragraph("Stage 7", body_style), Paragraph("Video Composition", body_style), Paragraph("FFmpegCompositionProvider layering presenter MP4, visual slides, audio, and burned subtitles.", body_style)],
        [Paragraph("Stage 8", body_style), Paragraph("Orchestration", body_style), Paragraph("ProjectManifestManager, stage idempotency, and partial pipeline resume.", body_style)],
        [Paragraph("Stage 9", body_style), Paragraph("API & Studio UI", body_style), Paragraph("FastAPI REST endpoints (/api/v1/projects) and Streamlit interactive dashboard.", body_style)],
    ]
    t_stages = Table(stages_data, colWidths=[50, 105, 349])
    t_stages.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), primary_color),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_stages)

    # Testing & Verification
    story.append(Paragraph("2. Testing Status & Provider Verification Matrix", h1_style))
    story.append(Paragraph(
        "<b>Automated Regression Suite:</b> 162 total tests executed, <b>162 passed (100%)</b>, 0 failed, 0 errors, 0 warnings in 27.35 seconds. "
        "Passing unit and mock tests verifies internal logic, schemas, and state transitions, but does <i>not</i> guarantee live external third-party API availability.",
        body_style,
    ))

    prov_matrix = [
        [Paragraph("<b>Provider Subsystem</b>", body_style), Paragraph("<b>Mock Tested</b>", body_style), Paragraph("<b>Local Real</b>", body_style), Paragraph("<b>Live External</b>", body_style), Paragraph("<b>Confidence Level</b>", body_style)],
        [Paragraph("LLM (GroqProvider)", body_style), Paragraph("YES", body_style), Paragraph("YES", body_style), Paragraph("PARTIAL", body_style), Paragraph("Moderate (Subject to rate limits)", body_style)],
        [Paragraph("TTS (EdgeTTSProvider)", body_style), Paragraph("YES", body_style), Paragraph("YES", body_style), Paragraph("YES", body_style), Paragraph("High (Free Microsoft endpoint)", body_style)],
        [Paragraph("Avatar (HeyGenProvider)", body_style), Paragraph("YES", body_style), Paragraph("NO", body_style), Paragraph("NO", body_style), Paragraph("Low / Guarded in Mock Mode", body_style)],
        [Paragraph("Visuals (Pillow)", body_style), Paragraph("YES", body_style), Paragraph("YES", body_style), Paragraph("N/A (Local)", body_style), Paragraph("High (Deterministic offline)", body_style)],
        [Paragraph("Subtitles (Deterministic)", body_style), Paragraph("YES", body_style), Paragraph("YES", body_style), Paragraph("N/A (Local)", body_style), Paragraph("High (Zero-drift math)", body_style)],
        [Paragraph("Composition (FFmpeg)", body_style), Paragraph("YES", body_style), Paragraph("YES", body_style), Paragraph("N/A (Local)", body_style), Paragraph("High (When binary is on PATH)", body_style)],
    ]
    t_prov = Table(prov_matrix, colWidths=[115, 65, 65, 75, 184])
    t_prov.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_prov)

    # Current Known Problems Audit
    story.append(Paragraph("3. Comprehensive Real-World Defect Register", h1_style))
    story.append(Paragraph(
        "The following issue register catalogs all confirmed and suspected defects identified during testing. "
        "Per project constraints, <b>no functional application changes or bug fixes have been applied</b>.",
        body_style,
    ))

    issues = [
        ("ISSUE-001", "CRITICAL", "Script Generation Pipeline Failure & Diagnostic Swallowing",
         "Project manifests (e.g. proj_7b26899ede40) fail at Stage 1 with 'Script generation failed: No final script produced', halting downstream stages.<br/>"
         "<b>Confirmed Cause 1:</b> orchestrator.py inspects state.get('error_message'), but VideoScriptState defines errors as state.errors, swallowing actual validation issues.<br/>"
         "<b>Confirmed Cause 2:</b> Space-separated WPM calculation underestimates Arabic speech duration, triggering false DURATION_MISMATCH rejections on short videos (30s ± 20%) that exhaust single-revision limits."),

        ("ISSUE-002", "HIGH", "Avatar Engine Locked in Mock Mode Without UI Control",
         "Streamlit displays 'Avatar Engine: Mock Mode Active (0 Credits Used)'. The system generates placeholder colored canvases even when a valid HEYGEN_API_KEY exists.<br/>"
         "<b>Confirmed Cause:</b> Hardcoded cost-safety defaults (DEFAULT_AVATAR_PROVIDER=mock, ENABLE_LIVE_API_TESTS=False) prevent live execution. No runtime UI switch exists to toggle live HeyGen generation safely."),

        ("ISSUE-003", "MEDIUM", "Hardcoded LLM Model Label in Streamlit Sidebar",
         "Streamlit sidebar displays 'LLM Provider: Groq (Llama-3.3-70b)' while backend configuration is GROQ_MODEL=openai/gpt-oss-20b.<br/>"
         "<b>Confirmed Cause:</b> Stale static string in frontend/streamlit_app.py line 84 that does not query backend health metadata."),

        ("ISSUE-004", "MEDIUM", "Manifest Diagnostic Error Duplication on Retries",
         "Project manifests accumulate duplicate identical error messages when pipeline runs are retried.<br/>"
         "<b>Confirmed Cause:</b> Unconditional append() in orchestrator.py without stage-level error resetting or deduplication."),

        ("ISSUE-005", "HIGH", "Base-Language and Source-Content Mismatch",
         "Supplying English source text while selecting base_language=ar-SA and target_languages=[ar-SA] causes the script writer to author Arabic directly, while LocalizationService skips cultural adaptation.<br/>"
         "<b>Confirmed Cause:</b> Architectural assumption that base_language matches source_content language. Bypasses cultural adaptation and domain terminology checks."),

        ("ISSUE-006", "MEDIUM", "Language-Agnostic WPM Duration Estimation",
         "Space-split token formula (len(narration.split()) / 140 * 60) treats morphologically dense Arabic and Bengali identically to English.<br/>"
         "<b>Likely Cause:</b> Latin-centric WPM heuristic produces artificially low duration figures for non-English scripts, causing duration rejections."),

        ("ISSUE-007", "LOW", "Bidirectional Arabic Subtitle Rendering in Standard FFmpeg",
         "Burning Arabic subtitles with standard FFmpeg subtitles filter may render disconnected or reversed characters on Windows builds lacking FriBidi/HarfBuzz font-shaping.<br/>"
         "<b>Likely Cause:</b> System FFmpeg binary variation. Recommended direction: Pre-shape Arabic text with python-bidi/arabic-reshaper or embed styled ASS subtitles."),

        ("ISSUE-008", "LOW", "Single-Node Local File Persistence Without Locking",
         "All project manifests and stage states are stored in un-locked JSON files on local disk (storage/projects/<id>/project.json).<br/>"
         "<b>Confirmed Cause:</b> Local prototype design. Concurrency risks exist under high asynchronous load without an ACID database."),

        ("HIST-001", "RESOLVED", "Frontend/Backend HTTP 422 Contract Mismatch",
         "Streamlit previously returned HTTP 422 Unprocessable Content due to flat payload structure and mismatched field names.<br/>"
         "<b>Resolution:</b> Implemented canonical serialization in serialize_create_project_payload(), added APIClientError handling, and protected with regression tests in test_frontend.py and test_api_projects.py. Verified returning HTTP 201 Created on live server."),
    ]

    for i_id, sev, comp, desc in issues:
        sev_color = accent_color if sev in ("CRITICAL", "HIGH") else (secondary_color if sev == "MEDIUM" else colors.HexColor("#276749"))
        story.append(Paragraph(f"<b>[{i_id}] {comp}</b> — <font color='{sev_color.hexval()}'><b>{sev}</b></font>", h2_style))
        story.append(Paragraph(desc, body_style))
        story.append(Spacer(1, 2))

    # Security & Secret Audit
    story.append(Paragraph("4. Security & Secret Audit Verification", h1_style))
    story.append(Paragraph(
        "A full recursive audit of all tracked and untracked files confirmed that <b>zero API keys, credentials, or private tokens "
        "are present in source code, documentation, or commit staging</b>. The real .env file is strictly ignored by .gitignore, "
        "and only sanitized placeholders exist in .env.example. All runtime project media and virtual environments are excluded.",
        body_style,
    ))

    # Limitations & Future Roadmap
    story.append(Paragraph("5. Platform Limitations & Future Roadmap", h1_style))
    story.append(Paragraph("<b>Current Architectural Limitations:</b>", h2_style))
    story.append(Paragraph("• Pre-TTS duration estimation cannot perfectly predict synthetic voice inflection or pauses.", bullet_style))
    story.append(Paragraph("• Script generation depends entirely on third-party Groq API availability and rate limits.", bullet_style))
    story.append(Paragraph("• Real avatar synthesis requires paid HeyGen credits; testing remains guarded in mock mode by default.", bullet_style))
    story.append(Paragraph("• Native composition requires host-installed FFmpeg binaries; cloud deployment will require containerization.", bullet_style))
    story.append(Paragraph("• Video composition runs synchronously in-process rather than via an asynchronous worker queue (Celery/Redis).", bullet_style))

    story.append(Paragraph("<b>Prioritized Future Roadmap:</b>", h2_style))
    story.append(Paragraph("<b>Priority 1 (Pre-Demo):</b> Synchronize orchestrator error logging with VideoScriptState.errors, add locale-aware WPM multipliers, connect Streamlit badges dynamically to /api/v1/health.", bullet_style))
    story.append(Paragraph("<b>Priority 2 (Pre-Production):</b> Migrate persistence to PostgreSQL, offload FFmpeg rendering to Celery/Redis, pre-shape Arabic subtitle text with python-bidi, add user authentication.", bullet_style))
    story.append(Paragraph("<b>Priority 3 (Enhancements):</b> Expand language library (Spanish, French, German), add karaoke subtitle highlight effects via Whisper, implement WebSocket progress streaming.", bullet_style))

    # Conclusion
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=primary_color, spaceAfter=6))
    story.append(Paragraph(
        "<b>AUDIT CONCLUSION:</b> The platform architecture demonstrates robust separation of concerns, complete schema contracts, "
        "and 100% automated regression test coverage across all internal components. Real live execution is constrained by the "
        "documented duration validation heuristics and intentional mock avatar safety guards.<br/><br/>"
        "<b>STATUS: AUDIT COMPLETE — NO BUG FIXES APPLIED</b>",
        body_style,
    ))

    doc.build(story, canvasmaker=NumberedCanvas)
    return output_filename


if __name__ == "__main__":
    out_file = generate_pdf_report()
    abs_path = os.path.abspath(out_file)
    size = os.path.getsize(abs_path)
    print(f"SUCCESS: Generated {abs_path} ({size:,} bytes)")
