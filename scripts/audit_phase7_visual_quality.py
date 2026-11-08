"""Visual Quality and Stream Audit Script for Phase 7 Acceptance.

Extracts:
1. Detailed ffprobe JSON for final composed video and every scene asset.
2. 12 distributed frames from final training_ar-SA.mp4 and builds a 4x3 contact sheet.
3. Multi-frame difference metrics (mean pixel absolute difference) for every scene clip
   to measure true motion vs static holds.
4. Saves all diagnostic artifacts into the conversation artifact directory.
"""

import json
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = Path(r"C:\Users\alimo\.gemini\antigravity\brain\1cef3562-e373-49d5-9114-c129543fdb2f")
DEMO_DIR = PROJECT_ROOT / "storage" / "demonstrations" / "phase7_showcase" / "proj_phase7_showcase"
FINAL_VIDEO = DEMO_DIR / "final" / "training_ar-SA.mp4"


def probe_file(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path.resolve()),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return json.loads(res.stdout)


def extract_frame(video_path: Path, timestamp: float, output_path: Path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path.resolve()),
        "-ss", str(timestamp),
        "-vframes", "1",
        str(output_path.resolve()),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0 or not output_path.exists():
        # Fallback without -ss (first frame)
        cmd_fallback = [
            "ffmpeg",
            "-y",
            "-i", str(video_path.resolve()),
            "-vframes", "1",
            str(output_path.resolve()),
        ]
        subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def measure_frame_difference(video_path: Path, t1: float, t2: float, tmp_dir: Path) -> float:
    f1_p = tmp_dir / f"diff_{t1:.2f}.png"
    f2_p = tmp_dir / f"diff_{t2:.2f}.png"
    extract_frame(video_path, t1, f1_p)
    extract_frame(video_path, t2, f2_p)
    im1 = np.array(Image.open(f1_p).convert("RGB"), dtype=np.float32)
    im2 = np.array(Image.open(f2_p).convert("RGB"), dtype=np.float32)
    diff = np.mean(np.abs(im1 - im2))
    f1_p.unlink(missing_ok=True)
    f2_p.unlink(missing_ok=True)
    return float(diff)


def main():
    print("=" * 80)
    print("PHASE 7 VISUAL QUALITY & STREAM AUDIT")
    print("=" * 80)

    if not FINAL_VIDEO.exists():
        print(f"Error: {FINAL_VIDEO} does not exist.")
        sys.exit(1)

    # 1. Probe Final Video
    final_probe = probe_file(FINAL_VIDEO)
    fmt = final_probe["format"]
    streams = final_probe["streams"]
    v_stream = next((s for s in streams if s["codec_type"] == "video"), None)
    a_stream = next((s for s in streams if s["codec_type"] == "audio"), None)

    print(f"\nFinal Video Path: {FINAL_VIDEO}")
    print(f"File Size:       {FINAL_VIDEO.stat().st_size:,} bytes")
    print(f"Duration:        {float(fmt['duration']):.3f}s")
    print(f"Bitrate:         {int(fmt.get('bit_rate', 0)):,} bps")
    print(f"Video Stream:    {v_stream['codec_name']} {v_stream['width']}x{v_stream['height']} @ {eval(v_stream['r_frame_rate']):.2f} fps")
    print(f"Audio Stream:    {a_stream['codec_name']} {a_stream['sample_rate']} Hz, {a_stream['channels']} channels")

    # 2. Extract 12 Distributed Frames
    dur = float(fmt["duration"])
    timestamps = [round((dur / 13) * (i + 1), 2) for i in range(12)]
    print(f"\nExtracting 12 Frames at timestamps: {timestamps}")

    frame_images = []
    tmp_frames_dir = DEMO_DIR / "audit_frames"
    tmp_frames_dir.mkdir(parents=True, exist_ok=True)

    for idx, ts in enumerate(timestamps):
        out_p = tmp_frames_dir / f"contact_frame_{idx + 1:02d}_{ts:.1f}s.png"
        extract_frame(FINAL_VIDEO, ts, out_p)
        frame_images.append((ts, Image.open(out_p).convert("RGB")))

    # 3. Create 4x3 Contact Sheet
    cell_w, cell_h = 480, 270
    contact_sheet = Image.new("RGB", (cell_w * 4, cell_h * 3), color=(20, 20, 25))
    draw = ImageDraw.Draw(contact_sheet)

    for idx, (ts, img) in enumerate(frame_images):
        col = idx % 4
        row = idx // 4
        x = col * cell_w
        y = row * cell_h
        thumb = img.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
        contact_sheet.paste(thumb, (x, y))

        # Overlay timestamp label
        label = f"Frame {idx + 1} | {ts:.1f}s"
        draw.rectangle([x + 10, y + 10, x + 160, y + 35], fill=(0, 0, 0, 180))
        draw.text((x + 15, y + 15), label, fill=(255, 255, 255))

    contact_sheet_path = ARTIFACT_DIR / "phase7_contact_sheet_12frames.png"
    contact_sheet.save(contact_sheet_path, quality=95)
    print(f"Generated Contact Sheet: {contact_sheet_path} ({contact_sheet_path.stat().st_size:,} bytes)")

    # 4. Measure Scene Clip True Motion (Pixel Difference between frames)
    scene_clips = [
        ("Scene 1 (Intro / HeyGen Presenter Full)", DEMO_DIR / "rendered" / "ar-SA" / "scene_1.mp4"),
        ("Scene 2 (Visual Demo / Veo B-Roll fallback)", DEMO_DIR / "rendered" / "ar-SA" / "scene_2.mp4"),
        ("Scene 3 (Explanation / Local Motion Visual)", DEMO_DIR / "rendered" / "ar-SA" / "scene_3.mp4"),
        ("Scene 4 (Outro / HeyGen Presenter Full)", DEMO_DIR / "rendered" / "ar-SA" / "scene_4.mp4"),
    ]

    print("\nScene Motion Analysis (Mean Pixel Difference between t=1.0s and t=2.0s):")
    motion_results = {}
    for name, clip_path in scene_clips:
        if clip_path.exists():
            probe = probe_file(clip_path)
            c_dur = float(probe["format"]["duration"])
            t1 = min(1.0, c_dur * 0.25)
            t2 = min(2.0, c_dur * 0.75)
            diff = measure_frame_difference(clip_path, t1, t2, tmp_frames_dir)
            motion_results[name] = {
                "path": str(clip_path),
                "duration": c_dur,
                "pixel_diff": diff,
                "has_motion": diff > 0.5,
            }
            print(f"  - {name}: diff={diff:.4f} | has_motion={'YES' if diff > 0.5 else 'NO (STATIC)'}")

    # 5. Measure Avatar Raw Clip
    avatar_clip_1 = DEMO_DIR / "avatars" / "ar-SA" / "scene_1.mp4"
    if avatar_clip_1.exists():
        av_diff = measure_frame_difference(avatar_clip_1, 0.5, 1.5, tmp_frames_dir)
        print(f"\nRaw Avatar Clip Motion (Scene 1): diff={av_diff:.4f} (Expected 0 for Mock solid color)")

    # Save summary report JSON
    audit_data = {
        "final_video": {
            "path": str(FINAL_VIDEO),
            "size_bytes": FINAL_VIDEO.stat().st_size,
            "duration": float(fmt["duration"]),
            "format": fmt["format_name"],
            "video_codec": v_stream["codec_name"],
            "audio_codec": a_stream["codec_name"],
            "width": v_stream["width"],
            "height": v_stream["height"],
            "fps": eval(v_stream["r_frame_rate"]),
        },
        "scenes": motion_results,
        "contact_sheet": str(contact_sheet_path),
        "timestamps": timestamps,
    }
    with open(ARTIFACT_DIR / "phase7_visual_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)

    print("\nAudit data persisted to phase7_visual_audit.json")


if __name__ == "__main__":
    main()
