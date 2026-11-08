import json
import re
import subprocess
from pathlib import Path

def get_duration(file_path):
    if not file_path or not Path(file_path).exists():
        return None
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return None

def get_last_subtitle_timestamp(sub_path):
    if not sub_path or not Path(sub_path).exists():
        return None
    content = Path(sub_path).read_text(encoding="utf-8")
    # For .ass or .srt, let's find timestamps
    if sub_path.suffix == ".ass":
        # Dialogue: 0,0:00:00.00,0:00:08.35,...
        matches = re.findall(r"Dialogue:\s*[^,]+,[^,]+,(\d+:\d+:\d+\.\d+)", content)
        if matches:
            last = matches[-1]
            parts = last.split(":")
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
    elif sub_path.suffix == ".srt":
        # 00:00:00,000 --> 00:00:08,350
        matches = re.findall(r"-->\s*(\d+:\d+:\d+[\.,]\d+)", content)
        if matches:
            last = matches[-1].replace(",", ".")
            parts = last.split(":")
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
    return None

def main():
    proj_dir = Path("storage/projects/proj_real_e2e_phishing")
    manifest_file = proj_dir / "project.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    locale = "ar-SA"
    script = manifest["localization_bundle"]["localized_scripts"][locale]

    print("=" * 100)
    print(f"TIMELINE AUDIT REPORT FOR {manifest['project_id']} ({locale})")
    print("=" * 100)

    rows = []
    total_words = 0
    total_pre_est = 0.0
    total_audio_dur = 0.0
    total_rendered_dur = 0.0

    for s in script["scenes"]:
        sc_id = s["scene_id"]
        narration = s["narration"]
        words = len(narration.split())
        total_words += words
        pre_est = s.get("estimated_duration_seconds", 0.0)
        total_pre_est += pre_est

        audio_file = proj_dir / "audio" / locale / f"{sc_id}.mp3"
        audio_dur = get_duration(audio_file)
        if audio_dur:
            total_audio_dur += audio_dur

        avatar_file = proj_dir / "avatars" / locale / f"{sc_id}_sadtalker.mp4"
        if not avatar_file.exists():
            avatar_file = proj_dir / "avatars" / locale / f"{sc_id}.mp4"
        avatar_dur = get_duration(avatar_file) if avatar_file.exists() else None

        visual_file = proj_dir / "visuals" / locale / f"{sc_id}.png"
        visual_exists = visual_file.exists()

        rendered_file = proj_dir / "rendered" / locale / f"{sc_id}.mp4"
        rendered_dur = get_duration(rendered_file)
        if rendered_dur:
            total_rendered_dur += rendered_dur

        sub_file = proj_dir / "subtitles" / locale / f"{sc_id}.ass"
        if not sub_file.exists():
            sub_file = proj_dir / "subtitles" / locale / f"{sc_id}.srt"
        last_sub_ts = get_last_subtitle_timestamp(sub_file)

        rows.append({
            "scene_id": sc_id,
            "scene_type": s.get("scene_type"),
            "words": words,
            "pre_est": pre_est,
            "audio_dur": audio_dur,
            "avatar_dur": avatar_dur,
            "visual_dur": "image" if visual_exists else "none",
            "rendered_dur": rendered_dur,
            "last_sub_ts": last_sub_ts,
        })

    # Header
    print(f"{'Scene ID':<10} | {'Type':<12} | {'Words':<6} | {'Pre-Est (s)':<11} | {'Audio (s)':<10} | {'Avatar (s)':<10} | {'Visual':<8} | {'Rendered (s)':<12} | {'Last Sub (s)':<12}")
    print("-" * 100)
    for r in rows:
        aud_s = f"{r['audio_dur']:.2f}" if r['audio_dur'] is not None else "N/A"
        av_s = f"{r['avatar_dur']:.2f}" if r['avatar_dur'] is not None else "N/A"
        rend_s = f"{r['rendered_dur']:.2f}" if r['rendered_dur'] is not None else "N/A"
        sub_s = f"{r['last_sub_ts']:.2f}" if r['last_sub_ts'] is not None else "N/A"
        print(f"{r['scene_id']:<10} | {r['scene_type']:<12} | {r['words']:<6} | {r['pre_est']:<11.1f} | {aud_s:<10} | {av_s:<10} | {r['visual_dur']:<8} | {rend_s:<12} | {sub_s:<12}")

    print("-" * 100)
    print(f"{'TOTALS':<10} | {'':<12} | {total_words:<6} | {total_pre_est:<11.1f} | {total_audio_dur:<10.2f} | {'':<10} | {'':<8} | {total_rendered_dur:<12.2f} |")
    print("=" * 100)

    final_sadtalker = proj_dir / "final" / f"training_{locale}_sadtalker.mp4"
    final_orig = proj_dir / "final" / f"training_{locale}.mp4"
    print(f"Final sadtalker video path: {final_sadtalker}")
    print(f"Final sadtalker video duration: {get_duration(final_sadtalker)} s")
    print(f"Original final video path: {final_orig}")
    print(f"Original final video duration: {get_duration(final_orig)} s")

if __name__ == "__main__":
    main()
