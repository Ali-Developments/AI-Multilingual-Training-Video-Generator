"""Dynamic Local Motion Visual Animator using Pillow and FFmpeg.

Produces high-definition (1920x1080 / 1114x1080) animated motion graphics,
instructional cards, security visual mockups, and interactive workflows
with smooth easing, animated highlights, cursors, badges, and progress lines.
Zero API cost, fully local, fast streaming execution.
"""

import math
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import LocalizedScene, SceneDraft


def _get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Load high-quality scalable font with graceful system fallbacks."""
    bold_candidates = [
        "segoeuib.ttf",
        "arialbd.ttf",
        "tahomabd.ttf",
        "DejaVuSans-Bold.ttf",
        "Helvetica-Bold.ttf",
    ]
    regular_candidates = [
        "segoeui.ttf",
        "arial.ttf",
        "tahoma.ttf",
        "DejaVuSans.ttf",
        "Helvetica.ttf",
    ]
    candidates = bold_candidates if bold else regular_candidates
    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(text: str, max_chars: int = 50) -> List[str]:
    """Word-wrap helper for multiline text blocks."""
    if not text:
        return []
    words = text.split()
    lines = []
    current_line: List[str] = []
    current_len = 0

    for word in words:
        if current_len + len(word) + 1 > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
        else:
            current_line.append(word)
            current_len += len(word) + 1

    if current_line:
        lines.append(" ".join(current_line))
    return lines


def _ease_out_cubic(t: float) -> float:
    """Smooth cubic deceleration curve: 0.0 -> 1.0."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _linear_step(t: float, start: float, end: float) -> float:
    """Normalized linear progression between start and end timestamps."""
    if end <= start:
        return 1.0 if t >= start else 0.0
    return max(0.0, min(1.0, (t - start) / (end - start)))


def _draw_ambient_canvas(
    width: int,
    height: int,
    t: float,
    custom_bg: Optional[Image.Image] = None,
) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    """Create a modern cinematic ambient dark canvas with subtle animated light shifts."""
    if custom_bg:
        img = custom_bg.copy().resize((width, height))
    else:
        img = Image.new("RGB", (width, height), color=(9, 13, 26))

    draw = ImageDraw.Draw(img)

    # Ambient animated soft radial glow fields
    pulse = math.sin(t * math.pi * 2) * 20
    draw.ellipse(
        [
            int(width * 0.1 - pulse),
            int(height * 0.1),
            int(width * 0.65 + pulse),
            int(height * 0.8),
        ],
        fill=(15, 24, 48),
    )
    draw.ellipse(
        [
            int(width * 0.45),
            int(height * 0.25 - pulse),
            int(width * 0.95 + pulse),
            int(height * 0.95),
        ],
        fill=(13, 34, 58),
    )

    # Top accent neon cyan/indigo stripe
    draw.rectangle([0, 0, width, 5], fill=(0, 229, 255))
    draw.rectangle([int(width * 0.5), 0, width, 5], fill=(79, 70, 229))

    # Bottom progress bar (moves with scene playback progress t)
    prog_w = max(4, int(width * t))
    draw.rectangle([0, height - 5, prog_w, height], fill=(0, 229, 255))

    return img, draw


def _draw_window_header(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    font: ImageFont.ImageFont,
) -> None:
    """Render macOS/Windows-style window titlebar with traffic-light dots."""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=(22, 32, 56))
    draw.rectangle([x, y + 20, x + w, y + h], fill=(22, 32, 56))  # Flatten bottom

    # Window dots
    draw.ellipse([x + 18, y + 12, x + 30, y + 24], fill=(255, 95, 86))
    draw.ellipse([x + 38, y + 12, x + 50, y + 24], fill=(255, 189, 46))
    draw.ellipse([x + 58, y + 12, x + 70, y + 24], fill=(39, 201, 63))

    # Title label
    draw.text((x + 88, y + 10), title, fill=(170, 185, 215), font=font)


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    bg_color: Tuple[int, int, int],
    text_color: Tuple[int, int, int],
    font: ImageFont.ImageFont,
    radius: int = 6,
    pad_x: int = 12,
    pad_y: int = 4,
) -> int:
    """Draw a compact rounded badge with centered text; returns total width."""
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    w = tw + pad_x * 2
    h = th + pad_y * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=bg_color)
    draw.text((x + pad_x, y + pad_y - bbox[1]), text, fill=text_color, font=font)
    return w


def _draw_cursor(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Draw a crisp vector computer mouse pointer cursor."""
    points = [
        (x, y),
        (x + 16, y + 36),
        (x + 23, y + 28),
        (x + 38, y + 34),
        (x + 42, y + 26),
        (x + 27, y + 20),
        (x + 36, y + 10),
    ]
    draw.polygon(points, fill=(255, 255, 255), outline=(10, 15, 25))


def _contains_rtl(text: str) -> bool:
    """Return True if text contains Arabic or Hebrew RTL script characters."""
    for ch in text or "":
        code = ord(ch)
        if (0x0590 <= code <= 0x08FF) or (0xFB50 <= code <= 0xFDFF) or (0xFE70 <= code <= 0xFEFF):
            return True
    return False


def _draw_text_bidi(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    fill: Tuple[int, int, int],
    font: ImageFont.ImageFont,
    max_right_x: Optional[int] = None,
) -> None:
    """Draw text with native HarfBuzz/Raqm RTL shaping when Arabic/Hebrew text is detected."""
    if not text:
        return
    if _contains_rtl(text):
        try:
            if max_right_x is not None:
                draw.text((max_right_x, xy[1]), text, fill=fill, font=font, direction="rtl", anchor="ra")
            else:
                draw.text(xy, text, fill=fill, font=font, direction="rtl")
            return
        except Exception:
            pass
    draw.text(xy, text, fill=fill, font=font)


def detect_motion_archetype(scene_data: Any) -> str:
    """Classify scene into an instructional motion archetype based on content and media plan."""
    title = getattr(scene_data, "title", "") or ""
    narration = getattr(scene_data, "narration", "") or ""
    purpose = getattr(scene_data, "purpose", "") or ""
    vis_dir = getattr(scene_data, "visual_direction", "") or getattr(scene_data, "visual_prompt", "") or ""
    ost = getattr(scene_data, "on_screen_text", "") or ""

    blob = f"{title} {narration} {purpose} {vis_dir} {ost}".lower()

    # Cybersecurity-specific archetypes ONLY trigger when genuine IT/security context is present
    cyber_context = any(
        k in blob
        for k in ("phish", "spoof", "malware", "ransomware", "soc", "quarantine", "cyber", "suspicious email", "verify url", "attachment")
    )
    if cyber_context:
        if any(k in blob for k in ("report", "incident", "soc", "contain", "quarantine", "alert team")):
            return "incident_response"
        if any(k in blob for k in ("safe", "handling", "attachment", "hover", "checklist", "verify url")):
            return "safe_handling"
        if any(k in blob for k in ("phish", "email", "domain", "sender", "spoof", "link", "indicator", "urgent")):
            return "email_security"

    media_type = str(getattr(scene_data, "media_type", "") or "").lower()
    scene_type = str(getattr(scene_data, "scene_type", "") or "").lower()
    if media_type in ("quiz", "title") or scene_type in ("quiz", "title"):
        return "general_concept"

    media_plan = getattr(scene_data, "media_plan", None)
    if media_plan is not None:
        if getattr(media_plan, "is_animated_demonstration", False):
            return "process_demonstration"
        if getattr(media_plan, "is_animated_demonstration", None) is False:
            return "general_concept"

    # Default instructional scenes with narration or visual direction use the dynamic process demonstration engine
    if narration.strip() or vis_dir.strip():
        return "process_demonstration"

    return "general_concept"


# =========================================================================
# Archetype 1: Email Security & Phishing Indicator Inspection
# =========================================================================

def _render_email_security_frame(
    width: int,
    height: int,
    sec: float,
    dur: float,
    scene: Any,
    custom_bg: Optional[Image.Image] = None,
) -> Image.Image:
    """Animated realistic email client inspection with highlighted spoofed domain and hovering cursor."""
    t = sec / max(dur, 0.1)
    img, draw = _draw_ambient_canvas(width, height, t, custom_bg)

    font_label = _get_font(18, bold=True)
    font_title = _get_font(34, bold=True)
    font_body = _get_font(22, bold=False)
    font_body_bold = _get_font(22, bold=True)
    font_badge = _get_font(16, bold=True)

    # 1. Category Header & Scene Title
    draw.text((80, 35), "CYBERSECURITY DEFENSE  |  THREAT INDICATOR INSPECTION", fill=(0, 229, 255), font=font_label)
    title_text = getattr(scene, "title", "Spotting Phishing Indicators & Verifying Sender")
    draw.text((80, 65), title_text, fill=(255, 255, 255), font=font_title)

    # 2. Email Client Card (Smooth Slide-In from bottom, 0.0s -> 0.7s)
    slide_prog = _ease_out_cubic(_linear_step(sec, 0.0, 0.7))
    start_y = height + 40
    target_y = 135
    card_y = int(start_y - slide_prog * (start_y - target_y))
    card_x = 80
    card_w = width - 160
    card_h = height - 200

    # Draw Glassmorphic Card Container
    draw.rounded_rectangle(
        [card_x, card_y, card_x + card_w, card_y + card_h],
        radius=16,
        fill=(16, 23, 42),
        outline=(38, 52, 85),
        width=2,
    )

    # Window Header Bar
    _draw_window_header(
        draw, card_x, card_y, card_w, 38,
        "Enterprise Mail Guard - Suspicious Message Analysis",
        _get_font(16, bold=False)
    )

    # Email Header Lines
    ey = card_y + 60
    draw.text((card_x + 35, ey), "From:", fill=(140, 160, 195), font=font_body_bold)
    draw.text((card_x + 120, ey), "IT Security Operations <security-alert@company-sec-update.com>", fill=(235, 242, 255), font=font_body)

    # Animated Domain Highlight Box (Wipes across @company-sec-update.com from 1.0s -> 2.0s)
    if sec > 0.9:
        wipe_prog = _linear_step(sec, 0.9, 1.8)
        box_x = card_x + 440
        box_w = int(390 * wipe_prog)
        draw.rounded_rectangle([box_x, ey - 3, box_x + box_w, ey + 28], radius=6, outline=(239, 68, 68), width=2)
        if wipe_prog >= 0.7:
            pulse = math.sin((sec - 1.5) * 6) * 0.5 + 0.5
            badge_color = (int(200 + 40 * pulse), 35, 35)
            _draw_badge(draw, box_x + box_w + 12, ey - 1, "MISMATCHED DOMAIN", badge_color, (255, 255, 255), font_badge)

    ey += 46
    draw.text((card_x + 35, ey), "Subject:", fill=(140, 160, 195), font=font_body_bold)
    draw.text((card_x + 120, ey), "URGENT: Immediate Account Verification Required Within 24 Hours", fill=(255, 125, 125), font=font_body_bold)
    _draw_badge(draw, card_x + card_w - 180, ey - 2, "URGENCY DETECTED", (180, 83, 9), (255, 255, 255), font_badge)

    ey += 46
    draw.rectangle([card_x + 30, ey, card_x + card_w - 30, ey + 1], fill=(35, 48, 78))

    # Email Body Content
    ey += 24
    draw.text((card_x + 35, ey), "Dear Employee,", fill=(220, 230, 245), font=font_body)
    ey += 34
    draw.text(
        (card_x + 35, ey),
        "An unauthorized sign-in attempt was detected on your corporate account. Please confirm your credentials immediately.",
        fill=(195, 210, 230),
        font=font_body,
    )
    ey += 30
    draw.text(
        (card_x + 35, ey),
        "Failure to verify will result in immediate suspension of workstation and VPN access.",
        fill=(195, 210, 230),
        font=font_body,
    )

    # Suspicious Action Link Button
    ey += 45
    btn_x = card_x + 35
    btn_w = 340
    btn_h = 44
    draw.rounded_rectangle([btn_x, ey, btn_x + btn_w, ey + btn_h], radius=8, fill=(30, 64, 175), outline=(59, 130, 246), width=1)
    draw.text((btn_x + 35, ey + 10), "Verify Account Credentials Now ->", fill=(255, 255, 255), font=_get_font(18, bold=True))

    # Animated Cursor (Glides from bottom right to button, 2.0s -> 3.2s)
    cur_x = int(card_x + card_w - 200)
    cur_y = int(card_y + card_h - 100)
    if sec > 1.8:
        cur_t = _ease_out_cubic(_linear_step(sec, 1.8, 3.0))
        cur_x = int(cur_x - cur_t * (cur_x - (btn_x + 220)))
        cur_y = int(cur_y - cur_t * (cur_y - (ey + 20)))

    _draw_cursor(draw, cur_x, cur_y)

    # Tooltip Popover (Reveals actual destination URL when cursor reaches link, 3.0s -> end)
    if sec > 2.8:
        tt_prog = _ease_out_cubic(_linear_step(sec, 2.8, 3.4))
        tt_w = int(580 * tt_prog)
        tt_y = ey + 56
        draw.rounded_rectangle([btn_x, tt_y, btn_x + tt_w, tt_y + 48], radius=8, fill=(12, 17, 30), outline=(239, 68, 68), width=2)
        if tt_prog > 0.7:
            draw.text((btn_x + 16, tt_y + 12), "REAL TARGET: http://login-spoof-portal.cc/harvest", fill=(255, 100, 100), font=_get_font(17, bold=True))
            _draw_badge(draw, btn_x + 430, tt_y + 10, "MALICIOUS", (220, 38, 38), (255, 255, 255), font_badge)

    return img


# =========================================================================
# Archetype 2: Safe Handling Rules & Verification Checklist
# =========================================================================

def _render_safe_handling_frame(
    width: int,
    height: int,
    sec: float,
    dur: float,
    scene: Any,
    custom_bg: Optional[Image.Image] = None,
) -> Image.Image:
    """Animated 3-step procedural checklist with pop-in cards and verification badges."""
    t = sec / max(dur, 0.1)
    img, draw = _draw_ambient_canvas(width, height, t, custom_bg)

    font_label = _get_font(18, bold=True)
    font_title = _get_font(34, bold=True)
    font_h2 = _get_font(24, bold=True)
    font_body = _get_font(20, bold=False)
    font_badge = _get_font(16, bold=True)

    # 1. Header
    draw.text((80, 35), "CYBER DEFENSE STANDARD  |  SAFE HANDLING PROCEDURES", fill=(0, 229, 255), font=font_label)
    title_text = getattr(scene, "title", "Safe Handling of Attachments & Links")
    draw.text((80, 65), title_text, fill=(255, 255, 255), font=font_title)

    # 3 Structured Rule Cards
    rules = [
        {
            "step": "RULE 01",
            "title": "Never Open Unexpected Attachments",
            "desc": "Invoices, ZIP files, or macros from unknown or unusual senders often deliver ransomware.",
            "status": "BLOCKED",
            "status_color": (220, 38, 38),
            "start": 0.2,
        },
        {
            "step": "RULE 02",
            "title": "Inspect & Preview All Links Before Clicking",
            "desc": "Hover your mouse over hyperlinked buttons to reveal the true URL destination in the status bar.",
            "status": "HOVER INSPECT",
            "status_color": (217, 119, 6),
            "start": 1.2,
        },
        {
            "step": "RULE 03",
            "title": "Verify Sender Domain via Alternate Channels",
            "desc": "Check internal phone directories or messaging before acting on urgent financial or password requests.",
            "status": "VERIFY FIRST",
            "status_color": (16, 185, 129),
            "start": 2.2,
        },
    ]

    card_x = 80
    card_w = width - 160
    card_h = 175
    y_gap = 25
    base_y = 150

    for idx, rule in enumerate(rules):
        rule_start = rule["start"]
        if sec < rule_start:
            continue

        prog = _ease_out_cubic(_linear_step(sec, rule_start, rule_start + 0.6))
        offset_x = int((1.0 - prog) * 200)
        curr_y = base_y + idx * (card_h + y_gap)

        # Active focus outline
        is_active = (sec >= rule_start and sec < (rules[idx + 1]["start"] if idx + 1 < len(rules) else dur))
        border_color = (0, 229, 255) if is_active else (40, 55, 88)
        border_w = 2 if is_active else 1

        draw.rounded_rectangle(
            [card_x + offset_x, curr_y, card_x + card_w, curr_y + card_h],
            radius=14,
            fill=(18, 25, 46),
            outline=border_color,
            width=border_w,
        )

        # Step Pill
        _draw_badge(draw, card_x + offset_x + 30, curr_y + 24, rule["step"], (30, 41, 69), (0, 229, 255), font_badge)

        # Rule Title & Status Badge
        draw.text((card_x + offset_x + 130, curr_y + 22), rule["title"], fill=(255, 255, 255), font=font_h2)
        _draw_badge(draw, card_x + card_w - 180, curr_y + 22, rule["status"], rule["status_color"], (255, 255, 255), font_badge)

        # Rule Description
        desc_lines = _wrap_text(rule["desc"], max_chars=78)[:2]
        dy = curr_y + 70
        for line in desc_lines:
            draw.text((card_x + offset_x + 30, dy), line, fill=(195, 210, 230), font=font_body)
            dy += 30

    return img


# =========================================================================
# Archetype 3: Incident Response & Threat Reporting Workflow
# =========================================================================

def _render_incident_response_frame(
    width: int,
    height: int,
    sec: float,
    dur: float,
    scene: Any,
    custom_bg: Optional[Image.Image] = None,
) -> Image.Image:
    """Animated reporting action card with animated flow-through into SOC containment."""
    t = sec / max(dur, 0.1)
    img, draw = _draw_ambient_canvas(width, height, t, custom_bg)

    font_label = _get_font(18, bold=True)
    font_title = _get_font(34, bold=True)
    font_h2 = _get_font(24, bold=True)
    font_body = _get_font(20, bold=False)
    font_badge = _get_font(16, bold=True)

    # 1. Header
    draw.text((80, 35), "INCIDENT RESPONSE WORKFLOW  |  ACTION PROTOCOL", fill=(0, 229, 255), font=font_label)
    title_text = getattr(scene, "title", "Reporting the Threat & Closing Reminder")
    draw.text((80, 65), title_text, fill=(255, 255, 255), font=font_title)

    # 2. Main Two-Panel Layout
    card_y = 150
    card_h = height - 230

    # Left Panel: User Action (Report Button)
    left_w = int((width - 200) * 0.42)
    left_x = 80
    draw.rounded_rectangle(
        [left_x, card_y, left_x + left_w, card_y + card_h],
        radius=16,
        fill=(16, 23, 44),
        outline=(38, 52, 85),
        width=2,
    )
    _draw_badge(draw, left_x + 30, card_y + 25, "USER ACTION", (30, 41, 69), (0, 229, 255), font_badge)
    draw.text((left_x + 30, card_y + 70), "Flag Suspicious Email", fill=(255, 255, 255), font=font_h2)

    lines = _wrap_text("When you spot an indicator, do not forward it to colleagues. Use the official reporting tool.", max_chars=34)[:3]
    ly = card_y + 115
    for l in lines:
        draw.text((left_x + 30, ly), l, fill=(185, 200, 225), font=font_body)
        ly += 30

    # Big Animated "Report Phishing" Button (clicks at 1.5s)
    btn_y = card_y + 240
    btn_w = left_w - 60
    btn_h = 56
    btn_x = left_x + 30

    is_clicked = (sec >= 1.5)
    btn_fill = (16, 185, 129) if is_clicked else (220, 38, 38)
    btn_text = "THREAT REPORTED [SUCCESS]" if is_clicked else "REPORT SUSPICIOUS EMAIL"

    draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=10, fill=btn_fill)
    draw.text((btn_x + 40, btn_y + 16), btn_text, fill=(255, 255, 255), font=_get_font(20, bold=True))

    # Animated cursor clicks button at 1.4s
    if sec < 2.0:
        cur_t = _ease_out_cubic(_linear_step(sec, 0.4, 1.4))
        cx = int(left_x + 400 - cur_t * 220)
        cy = int(card_y + 360 - cur_t * 100)
        _draw_cursor(draw, cx, cy)

    # Right Panel: SOC Response Pipeline
    right_x = left_x + left_w + 40
    right_w = width - right_x - 80
    draw.rounded_rectangle(
        [right_x, card_y, right_x + right_w, card_y + card_h],
        radius=16,
        fill=(16, 23, 44),
        outline=(38, 52, 85),
        width=2,
    )
    _draw_badge(draw, right_x + 30, card_y + 25, "RESPONSE PIPELINE", (30, 41, 69), (0, 229, 255), font_badge)
    draw.text((right_x + 30, card_y + 70), "Cyber Security Operations (SOC)", fill=(255, 255, 255), font=font_h2)

    # Workflow Steps
    steps = [
        {"title": "1. Automated Triage & Header Analysis", "start": 1.7},
        {"title": "2. Malicious Domain Blocked Globally", "start": 2.5},
        {"title": "3. Dangerous Attachments Quarantined", "start": 3.3},
        {"title": "4. Enterprise Workstations Protected", "start": 4.1},
    ]

    sy = card_y + 130
    for s_idx, st in enumerate(steps):
        if sec < st["start"]:
            continue
        s_prog = _ease_out_cubic(_linear_step(sec, st["start"], st["start"] + 0.5))
        offset = int((1.0 - s_prog) * 60)

        draw.rounded_rectangle(
            [right_x + 30 + offset, sy, right_x + right_w - 30, sy + 46],
            radius=8,
            fill=(22, 32, 58),
            outline=(16, 185, 129),
            width=1,
        )
        draw.text((right_x + 50 + offset, sy + 11), st["title"], fill=(235, 245, 255), font=_get_font(18, bold=True))
        _draw_badge(draw, right_x + right_w - 110, sy + 9, "ACTIVE", (16, 185, 129), (255, 255, 255), font_badge)
        sy += 60

    return img


# =========================================================================
# Archetype 4: General Concept & Educational Infographic
# =========================================================================

def _render_general_concept_frame(
    width: int,
    height: int,
    sec: float,
    dur: float,
    scene: Any,
    custom_bg: Optional[Image.Image] = None,
) -> Image.Image:
    """Animated general instructional card with progressive bullet reveals."""
    t = sec / max(dur, 0.1)
    img, draw = _draw_ambient_canvas(width, height, t, custom_bg)

    font_label = _get_font(18, bold=True)
    font_title = _get_font(34, bold=True)
    font_h2 = _get_font(26, bold=True)
    font_body = _get_font(22, bold=False)
    font_badge = _get_font(16, bold=True)

    # 1. Header
    draw.text((80, 35), "TRAINING MODULE  |  CORE INSTRUCTION", fill=(0, 229, 255), font=font_label)
    title_text = getattr(scene, "title", "Key Educational Principles")
    draw.text((80, 65), title_text, fill=(255, 255, 255), font=font_title)

    # Main Card
    card_x = 80
    card_y = 150
    card_w = width - 160
    card_h = height - 230

    slide_prog = _ease_out_cubic(_linear_step(sec, 0.0, 0.6))
    cur_y = int(card_y + (1.0 - slide_prog) * 150)

    draw.rounded_rectangle(
        [card_x, cur_y, card_x + card_w, cur_y + card_h],
        radius=16,
        fill=(16, 23, 44),
        outline=(38, 52, 85),
        width=2,
    )

    ost = getattr(scene, "on_screen_text", "") or ""
    if ost:
        _draw_badge(draw, card_x + 40, cur_y + 30, ost.upper(), (30, 41, 69), (0, 229, 255), font_badge)

    narr = getattr(scene, "narration", "") or ""
    narr_lines = _wrap_text(narr, max_chars=60)[:4]
    ny = cur_y + 80
    for line in narr_lines:
        draw.text((card_x + 40, ny), line, fill=(240, 245, 255), font=font_h2)
        ny += 42

    return img


# =========================================================================
# Archetype 5: Generic Narration-Synchronized Process Demonstration
# =========================================================================

def _draw_action_simulation(
    draw: ImageDraw.ImageDraw,
    box_x: int,
    box_y: int,
    box_w: int,
    box_h: int,
    movement: str,
    action_verb: str,
    step_t: float,
    sec: float,
    objects: List[str],
) -> None:
    """
    Draw a continuous, frame-accurate procedural 2D vector demonstration
    corresponding to the active instructional action and movement pattern.
    """
    cx = box_x + box_w // 2
    cy = box_y + box_h // 2
    r_main = min(box_w, box_h) // 4

    # Subtle grid stage backdrop
    for gx in range(box_x + 40, box_x + box_w, 60):
        draw.line([(gx, box_y + 20), (gx, box_y + box_h - 20)], fill=(20, 31, 56), width=1)
    for gy in range(box_y + 40, box_y + box_h, 60):
        draw.line([(box_x + 20, gy), (box_x + box_w - 20, gy)], fill=(20, 31, 56), width=1)

    if movement == "heat_pulse":
        # Thermal vessel + rising heat/steam waves + live temperature gauge
        vessel_w, vessel_h = int(r_main * 2.2), int(r_main * 1.1)
        vx0, vy0 = cx - vessel_w // 2, cy + 15
        vx1, vy1 = cx + vessel_w // 2, cy + 15 + vessel_h
        # Glowing heat rings beneath vessel
        heat_pulse = 0.5 + 0.5 * math.sin(sec * 5.0)
        glow_r = int(220 + 35 * heat_pulse)
        glow_g = int(85 + 65 * step_t)
        draw.ellipse([vx0 + 15, vy1 - 12, vx1 - 15, vy1 + 26], fill=(glow_r, glow_g, 25))
        draw.rounded_rectangle([vx0, vy0, vx1, vy1], radius=22, fill=(32, 46, 78), outline=(251, 146, 60), width=3)
        # Rising animated steam/convection arcs
        for i in range(5):
            phase = (sec * 1.6 + i * 0.35) % 1.0
            sx = vx0 + 35 + i * ((vessel_w - 70) // 4) + int(math.sin(sec * 4.0 + i) * 10)
            sy = int(vy0 - 15 - phase * (r_main * 1.25))
            rad = int(8 + (1.0 - phase) * 10)
            alpha_tint = int(130 + 100 * (1.0 - phase))
            draw.ellipse([sx - rad, sy - rad, sx + rad, sy + rad], outline=(alpha_tint, 215, 255), width=2)
        # Temperature progress bar
        gx0, gy0 = box_x + 40, box_y + box_h - 46
        gw = box_w - 80
        draw.rounded_rectangle([gx0, gy0, gx0 + gw, gy0 + 14], radius=7, fill=(24, 34, 58))
        fill_w = max(14, int(gw * max(0.12, step_t)))
        draw.rounded_rectangle([gx0, gy0, gx0 + fill_w, gy0 + 14], radius=7, fill=(249, 115, 22))

    elif movement == "stir_circular":
        # Mixing vessel with rotating orbital particles and stirring paddle
        draw.ellipse([cx - r_main - 24, cy - r_main - 24, cx + r_main + 24, cy + r_main + 24], fill=(22, 34, 62), outline=(0, 229, 255), width=3)
        draw.ellipse([cx - r_main, cy - r_main, cx + r_main, cy + r_main], fill=(28, 44, 78), outline=(56, 189, 248), width=2)
        # Swirling orbital particles
        for i in range(8):
            angle = sec * 2.8 + i * (math.pi / 4.0)
            dist = r_main * (0.38 + 0.38 * ((i % 3) / 2.0))
            px = int(cx + math.cos(angle) * dist)
            py = int(cy + math.sin(angle) * dist)
            pr = 9 + (i % 3) * 3
            col = (0, 229, 255) if i % 2 == 0 else (250, 204, 21)
            draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=col)
        # Stirring tool arm rotating smoothly
        arm_angle = sec * 3.2
        ax = int(cx + math.cos(arm_angle) * (r_main * 0.72))
        ay = int(cy + math.sin(arm_angle) * (r_main * 0.72))
        draw.line([(cx, cy - r_main - 45), (ax, ay)], fill=(248, 250, 252), width=6)
        draw.ellipse([ax - 12, ay - 12, ax + 12, ay + 12], fill=(248, 250, 252))

    elif movement == "pour_stream":
        # Source container tilting + flowing stream + target container filling proportionally to step_t
        src_x, src_y = cx - int(r_main * 1.15), cy - int(r_main * 0.95)
        draw.rounded_rectangle([src_x - 55, src_y - 32, src_x + 55, src_y + 32], radius=12, fill=(45, 62, 102), outline=(0, 229, 255), width=2)
        # Animated pouring stream droplets
        stream_x = cx + 10
        stream_top = src_y + 18
        target_top = cy + 10
        target_bot = cy + int(r_main * 1.15)
        draw.line([(src_x + 48, src_y + 10), (stream_x, target_bot - 15)], fill=(56, 189, 248), width=8)
        for i in range(6):
            drop_p = (sec * 2.2 + i / 6.0) % 1.0
            dx = int((src_x + 48) + drop_p * (stream_x - (src_x + 48)))
            dy = int((src_y + 10) + drop_p * (target_bot - 25 - (src_y + 10)))
            draw.ellipse([dx - 7, dy - 7, dx + 7, dy + 7], fill=(125, 211, 252))
        # Target vessel with rising fill level
        tw = int(r_main * 1.8)
        tx0, tx1 = cx - tw // 2 + 10, cx + tw // 2 + 10
        draw.rounded_rectangle([tx0, target_top, tx1, target_bot], radius=16, fill=(22, 33, 58), outline=(148, 163, 184), width=3)
        fill_h = int((target_bot - target_top - 12) * max(0.1, min(0.95, step_t)))
        draw.rounded_rectangle([tx0 + 6, target_bot - 6 - fill_h, tx1 - 6, target_bot - 6], radius=10, fill=(14, 165, 233))

    elif movement == "chop_rhythm":
        # Workboard + object being sliced into animated pieces with rhythmic blade motion
        board_w, board_h = int(r_main * 2.5), int(r_main * 1.2)
        bx0, by0 = cx - board_w // 2, cy - board_h // 2 + 25
        draw.rounded_rectangle([bx0, by0, bx0 + board_w, by0 + board_h], radius=16, fill=(38, 48, 74), outline=(99, 102, 241), width=2)
        # Pieces separating progressively with step_t
        slices = 5
        piece_w = 34
        base_x = cx - 95
        for i in range(slices):
            sep = int(step_t * i * 16)
            px0 = base_x + i * (piece_w + 4) + sep
            py0 = cy + 5
            draw.rounded_rectangle([px0, py0, px0 + piece_w, py0 + 48], radius=8, fill=(251, 191, 36) if i % 2 == 0 else (245, 158, 11))
        # Rhythmic vertical blade guide
        chop_osc = abs(math.sin(sec * 6.0))
        blade_x = int(base_x + step_t * 170)
        blade_y = int(cy - 65 + chop_osc * 55)
        draw.rounded_rectangle([blade_x - 4, blade_y, blade_x + 4, blade_y + 72], radius=3, fill=(226, 232, 240))
        draw.rounded_rectangle([blade_x - 16, blade_y - 16, blade_x + 16, blade_y + 4], radius=6, fill=(0, 229, 255))

    elif movement == "layer_stack":
        # Progressive multi-layer assembly sliding into container
        tray_w, tray_h = int(r_main * 2.4), int(r_main * 1.5)
        tx0, ty0 = cx - tray_w // 2, cy - tray_h // 2 + 15
        draw.rounded_rectangle([tx0, ty0, tx0 + tray_w, ty0 + tray_h], radius=16, fill=(22, 32, 56), outline=(148, 163, 184), width=3)
        layer_colors = [(250, 204, 21), (239, 68, 68), (245, 158, 11), (248, 250, 252)]
        num_layers = len(layer_colors)
        layer_h = (tray_h - 32) // num_layers
        for i, col in enumerate(layer_colors):
            l_prog = _ease_out_cubic(_linear_step(step_t, i * 0.22, i * 0.22 + 0.28))
            if l_prog <= 0.01:
                continue
            target_y = ty0 + tray_h - 14 - (i + 1) * layer_h
            cur_y = int(target_y - (1.0 - l_prog) * 90)
            draw.rounded_rectangle([tx0 + 14, cur_y, tx0 + tray_w - 14, cur_y + layer_h - 6], radius=8, fill=col)

    elif movement == "orbit_flow":
        # Connected workflow/circuit/code nodes with traveling signal pulses
        nodes = [
            (cx - int(r_main * 1.25), cy),
            (cx, cy - int(r_main * 0.72)),
            (cx + int(r_main * 1.25), cy),
            (cx, cy + int(r_main * 0.72)),
        ]
        for i in range(len(nodes)):
            n1 = nodes[i]
            n2 = nodes[(i + 1) % len(nodes)]
            draw.line([n1, n2], fill=(51, 65, 105), width=4)
            # Traveling data/energy pulse
            p_t = (sec * 0.9 + i * 0.25) % 1.0
            px = int(n1[0] + (n2[0] - n1[0]) * p_t)
            py = int(n1[1] + (n2[1] - n1[1]) * p_t)
            draw.ellipse([px - 9, py - 9, px + 9, py + 9], fill=(0, 229, 255))
        for i, (nx, ny) in enumerate(nodes):
            active = int(step_t * len(nodes)) % len(nodes) == i
            outline = (0, 229, 255) if active else (99, 102, 241)
            draw.ellipse([nx - 34, ny - 34, nx + 34, ny + 34], fill=(22, 34, 64), outline=outline, width=3)

    elif movement == "highlight_scan":
        # Precision inspection / measurement reticle scanning smoothly
        draw.rounded_rectangle([cx - r_main, cy - r_main, cx + r_main, cy + r_main], radius=18, fill=(22, 34, 62), outline=(56, 189, 248), width=2)
        scan_y = int((cy - r_main + 12) + ((math.sin(sec * 2.5) * 0.5 + 0.5) * (r_main * 2 - 24)))
        draw.line([(cx - r_main + 8, scan_y), (cx + r_main - 8, scan_y)], fill=(0, 229, 255), width=4)
        # Concentric target rings
        ring_r = int(32 + 12 * math.sin(sec * 4.0))
        draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], outline=(16, 185, 129), width=3)
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(16, 185, 129))

    else:
        # showcase_reveal / slide_in: radiating spotlight + animated focus rings
        pulse_r = int(r_main * (0.75 + 0.18 * math.sin(sec * 3.0)))
        draw.ellipse([cx - pulse_r - 20, cy - pulse_r - 20, cx + pulse_r + 20, cy + pulse_r + 20], outline=(79, 70, 229), width=3)
        draw.ellipse([cx - pulse_r, cy - pulse_r, cx + pulse_r, cy + pulse_r], fill=(24, 38, 72), outline=(0, 229, 255), width=3)
        # Animated progress arc indicator (rotating satellite dot)
        angle = sec * 2.2
        sx = int(cx + math.cos(angle) * pulse_r)
        sy = int(cy + math.sin(angle) * pulse_r)
        draw.ellipse([sx - 10, sy - 10, sx + 10, sy + 10], fill=(0, 229, 255))

    # Draw active object pills along the top of the simulation stage
    font_obj = _get_font(18, bold=True)
    ox = box_x + 24
    oy = box_y + 20
    for obj in (objects or [])[:4]:
        pill_w = _draw_badge(draw, ox, oy, obj[:22], (30, 44, 78), (224, 242, 254), font_obj, radius=8, pad_x=14, pad_y=6)
        ox += pill_w + 12
        if ox > box_x + box_w - 160:
            break


def _render_process_demonstration_frame(
    width: int,
    height: int,
    sec: float,
    dur: float,
    scene: Any,
    custom_bg: Optional[Image.Image] = None,
) -> Image.Image:
    """
    Generic narration-synchronized process demonstration renderer.
    Animates real-time procedural visual actions alongside a live step timeline
    so the visual demonstration stays continuously active and synced to speech.
    """
    t = max(0.0, min(1.0, sec / max(dur, 0.1)))
    img, draw = _draw_ambient_canvas(width, height, t, custom_bg)

    font_label = _get_font(18, bold=True)
    font_title = _get_font(34, bold=True)
    font_h2 = _get_font(22, bold=True)
    font_body = _get_font(19, bold=False)
    font_badge = _get_font(15, bold=True)

    # Resolve or synthesize SceneMediaPlan animation steps
    media_plan = getattr(scene, "media_plan", None)
    steps = list(getattr(media_plan, "animation_sequence", None) or []) if media_plan else []
    if not steps:
        try:
            from app.workflows.storyboard_planner import StoryboardPlanner
            media_plan = StoryboardPlanner.build_demonstration_plan(scene)
            steps = list(media_plan.animation_sequence or [])
        except Exception:
            steps = []

    # Identify active step at current normalized timestamp t
    active_idx = 0
    active_step = None
    for idx, st in enumerate(steps):
        if st.start_ratio <= t <= st.end_ratio or (idx == len(steps) - 1 and t >= st.start_ratio):
            active_idx = idx
            active_step = st
            break
    if active_step is None and steps:
        active_step = steps[0]

    step_start = getattr(active_step, "start_ratio", 0.0) if active_step else 0.0
    step_end = getattr(active_step, "end_ratio", 1.0) if active_step else 1.0
    step_t = _linear_step(t, step_start, max(step_end, step_start + 0.01))

    action_verb = getattr(active_step, "action_verb", "highlight") if active_step else "highlight"
    movement = getattr(active_step, "movement", "showcase_reveal") if active_step else "showcase_reveal"
    active_objects = (
        list(getattr(active_step, "objects", None) or [])
        or list(getattr(media_plan, "required_objects", None) or [])
    )

    # 1. Header Banner
    scene_title = getattr(scene, "title", "Instructional Demonstration") or "Instructional Demonstration"
    header_tag = f"VISUAL DEMONSTRATION  |  ACTION: {action_verb.upper()}"
    draw.text((70, 30), header_tag, fill=(0, 229, 255), font=font_label)
    _draw_text_bidi(draw, (70, 62), scene_title, fill=(255, 255, 255), font=font_title, max_right_x=width - 70)

    # 2. Two-Zone Layout: Left Visual Action Stage (56%) + Right Step Timeline (40%)
    stage_x = 70
    stage_y = 130
    stage_w = int((width - 170) * 0.57)
    stage_h = height - 245

    draw.rounded_rectangle(
        [stage_x, stage_y, stage_x + stage_w, stage_y + stage_h],
        radius=18,
        fill=(15, 23, 42),
        outline=(0, 229, 255),
        width=2,
    )

    # Draw continuous vector process simulation inside left stage
    _draw_action_simulation(
        draw=draw,
        box_x=stage_x + 12,
        box_y=stage_y + 12,
        box_w=stage_w - 24,
        box_h=stage_h - 115,
        movement=movement,
        action_verb=action_verb,
        step_t=step_t,
        sec=sec,
        objects=active_objects,
    )

    # Synchronized active narration segment callout at bottom of left stage
    callout_y = stage_y + stage_h - 94
    draw.rounded_rectangle(
        [stage_x + 18, callout_y, stage_x + stage_w - 18, stage_y + stage_h - 14],
        radius=12,
        fill=(22, 34, 62),
        outline=(56, 189, 248),
        width=1,
    )
    active_narr = (
        getattr(active_step, "narration_segment", "")
        or getattr(scene, "visual_direction", "")
        or getattr(scene, "narration", "")
    )
    narr_lines = _wrap_text(active_narr, max_chars=52)[:2]
    ny = callout_y + 14
    for line in narr_lines:
        _draw_text_bidi(draw, (stage_x + 34, ny), line, fill=(241, 245, 249), font=font_body, max_right_x=stage_x + stage_w - 34)
        ny += 30

    # 3. Right Panel: Synchronized Step Progression Timeline
    panel_x = stage_x + stage_w + 30
    panel_w = width - panel_x - 70
    draw.rounded_rectangle(
        [panel_x, stage_y, panel_x + panel_w, stage_y + stage_h],
        radius=18,
        fill=(15, 23, 42),
        outline=(40, 56, 92),
        width=2,
    )
    _draw_badge(draw, panel_x + 24, stage_y + 22, "STEP TIMELINE", (30, 41, 69), (0, 229, 255), font_badge)
    step_counter = f"{active_idx + 1} / {max(len(steps), 1)}"
    draw.text((panel_x + panel_w - 90, stage_y + 24), step_counter, fill=(148, 163, 184), font=font_label)

    # Render each animation step card with live state
    card_y = stage_y + 72
    avail_h = stage_h - 92
    max_cards = max(len(steps[:5]), 1)
    card_h = min(132, (avail_h - (max_cards - 1) * 14) // max_cards)

    for idx, st in enumerate(steps[:5]):
        is_done = idx < active_idx
        is_active = idx == active_idx
        bg_fill = (24, 39, 72) if is_active else ((18, 30, 54) if is_done else (16, 24, 44))
        border_col = (0, 229, 255) if is_active else ((16, 185, 129) if is_done else (38, 52, 85))
        draw.rounded_rectangle(
            [panel_x + 20, card_y, panel_x + panel_w - 20, card_y + card_h],
            radius=12,
            fill=bg_fill,
            outline=border_col,
            width=2 if is_active else 1,
        )

        status_text = "ACTIVE" if is_active else ("DONE" if is_done else "NEXT")
        status_bg = (0, 180, 216) if is_active else ((16, 185, 129) if is_done else (51, 65, 85))
        _draw_badge(draw, panel_x + 34, card_y + 14, f"STEP {st.step_index}", (30, 41, 69), (0, 229, 255), font_badge)
        _draw_badge(draw, panel_x + panel_w - 118, card_y + 14, status_text, status_bg, (255, 255, 255), font_badge)

        lbl_lines = _wrap_text(st.label, max_chars=36)[:2]
        ly = card_y + 48
        for l in lbl_lines:
            _draw_text_bidi(draw, (panel_x + 34, ly), l, fill=(255, 255, 255) if is_active else (190, 205, 230), font=font_h2 if is_active else font_body, max_right_x=panel_x + panel_w - 34)
            ly += 26

        # Live per-step progress bar for active step
        if is_active:
            bar_x = panel_x + 34
            bar_w = panel_w - 68
            bar_y = card_y + card_h - 14
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 6], radius=3, fill=(30, 41, 69))
            draw.rounded_rectangle([bar_x, bar_y, bar_x + max(6, int(bar_w * step_t)), bar_y + 6], radius=3, fill=(0, 229, 255))

        card_y += card_h + 14

    return img


# =========================================================================
# Main Streaming Video Generation Engine
# =========================================================================

def generate_animated_motion_video(
    scene: Any,
    duration_seconds: float,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 25,
    custom_background_path: Optional[Path] = None,
) -> Path:
    """
    Render continuous 25 FPS true-motion instructional video stream directly to MP4 via FFmpeg.
    Guarantees genuine animation on every single frame without static holds.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(duration_seconds, 1.0)
    safe_fps = max(int(fps or 25), 1)
    total_frames = max(int(round(dur * safe_fps)), 1)

    archetype = detect_motion_archetype(scene)
    logger.info(
        "Rendering animated motion graphic (%s) for scene '%s' (dur=%.2fs, frames=%d)",
        archetype, getattr(scene, "scene_id", "scene"), dur, total_frames
    )

    custom_bg = None
    if custom_background_path and custom_background_path.exists():
        try:
            custom_bg = Image.open(custom_background_path).convert("RGB")
        except Exception:
            custom_bg = None

    ffmpeg_cmd = [
        settings.FFMPEG_BINARY_PATH,
        "-y",
        "-nostats",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(safe_fps),
        "-i", "-",
        "-c:v", settings.VIDEO_CODEC,
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        str(output_path.resolve()),
    ]

    p = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        for f_idx in range(total_frames):
            if p.poll() is not None:
                break
            sec = f_idx / safe_fps
            if archetype == "email_security":
                frame_img = _render_email_security_frame(width, height, sec, dur, scene, custom_bg)
            elif archetype == "safe_handling":
                frame_img = _render_safe_handling_frame(width, height, sec, dur, scene, custom_bg)
            elif archetype == "incident_response":
                frame_img = _render_incident_response_frame(width, height, sec, dur, scene, custom_bg)
            elif archetype == "process_demonstration":
                frame_img = _render_process_demonstration_frame(width, height, sec, dur, scene, custom_bg)
            else:
                frame_img = _render_general_concept_frame(width, height, sec, dur, scene, custom_bg)

            try:
                p.stdin.write(frame_img.tobytes())
            except (BrokenPipeError, OSError):
                break

        if p.stdin and not p.stdin.closed:
            try:
                p.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        p.wait(timeout=60)
        if p.returncode != 0:
            logger.error("FFmpeg motion video generation failed with exit code %d", p.returncode)
            raise RuntimeError(f"FFmpeg motion encoding failed with exit code {p.returncode}")
    except Exception as ex:
        p.kill()
        logger.exception("Error generating animated motion video for scene '%s': %s", getattr(scene, "scene_id", ""), ex)
        raise

    return output_path

