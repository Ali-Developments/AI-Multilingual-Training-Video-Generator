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


def detect_motion_archetype(scene_data: Any) -> str:
    """Classify scene into an instructional motion archetype based on content."""
    title = getattr(scene_data, "title", "") or ""
    narration = getattr(scene_data, "narration", "") or ""
    purpose = getattr(scene_data, "purpose", "") or ""
    vis_dir = getattr(scene_data, "visual_direction", "") or getattr(scene_data, "visual_prompt", "") or ""
    ost = getattr(scene_data, "on_screen_text", "") or ""

    blob = f"{title} {narration} {purpose} {vis_dir} {ost}".lower()

    if any(k in blob for k in ("report", "incident", "soc", "delete", "contain", "quarantine", "workflow", "alert team")):
        return "incident_response"
    if any(k in blob for k in ("safe", "handling", "attachment", "hover", "caution", "checklist", "verify url", "rule")):
        return "safe_handling"
    if any(k in blob for k in ("phish", "email", "domain", "sender", "spoof", "link", "cue", "indicator", "urgent")):
        return "email_security"
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

