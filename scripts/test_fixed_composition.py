import json
import subprocess
from pathlib import Path

def get_duration(file_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return float(res.stdout.strip())

def main():
    proj_dir = Path("storage/projects/proj_real_e2e_phishing")
    locale = "ar-SA"

    test_rendered_dir = proj_dir / "rendered_verified" / locale
    test_rendered_dir.mkdir(parents=True, exist_ok=True)

    # Let's inspect each scene and render with normalized audio: 48kHz, stereo, exact duration
    scenes = [
        {"id": "scene_1", "has_avatar": True, "dur": 8.35},
        {"id": "scene_2", "has_avatar": False, "dur": 7.92},
        {"id": "scene_3", "has_avatar": False, "dur": 10.49},
        {"id": "scene_4", "has_avatar": False, "dur": 8.95},
        {"id": "scene_5", "has_avatar": False, "dur": 8.50},
    ]

    rendered_files = []
    norm_filter = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1"

    for s in scenes:
        sc_id = s["id"]
        dur = s["dur"]
        out_mp4 = test_rendered_dir / f"{sc_id}.mp4"
        audio_file = proj_dir / "audio" / locale / f"{sc_id}.mp3"
        sub_file = proj_dir / "subtitles" / locale / f"{sc_id}.ass"
        escaped_sub = str(sub_file.resolve()).replace("\\", "/").replace(":", "\\:")
        sub_filter = f"ass='{escaped_sub}':shaping=complex"
        combined_filter = f"{norm_filter},{sub_filter}"

        if s["has_avatar"]:
            av_file = proj_dir / "avatars" / locale / f"{sc_id}_sadtalker.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(av_file.resolve()),
                "-i", str(audio_file.resolve()),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-vf", combined_filter,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "25",
                "-c:a", "aac",
                "-ar", "48000",
                "-ac", "2",
                "-b:a", "192k",
                "-t", str(dur),
                str(out_mp4.resolve()),
            ]
        else:
            vis_file = proj_dir / "visuals" / locale / f"{sc_id}.png"
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(vis_file.resolve()),
                "-i", str(audio_file.resolve()),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-vf", combined_filter,
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-pix_fmt", "yuv420p",
                "-r", "25",
                "-c:a", "aac",
                "-ar", "48000",
                "-ac", "2",
                "-b:a", "192k",
                "-shortest",
                "-t", str(dur),
                str(out_mp4.resolve()),
            ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error rendering {sc_id}: {res.stderr}")
            return
        measured = get_duration(out_mp4)
        print(f"Rendered {sc_id}: target={dur}s, measured={measured:.2f}s")
        rendered_files.append(out_mp4)

    # Now concatenate
    final_out = proj_dir / "final" / f"training_{locale}_sadtalker_timing_fixed.mp4"
    final_out.parent.mkdir(parents=True, exist_ok=True)
    concat_txt = test_rendered_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{f.resolve().as_posix()}'" for f in rendered_files), encoding="utf-8")

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_txt.resolve()),
        "-c", "copy",
        str(final_out.resolve()),
    ]
    res_concat = subprocess.run(concat_cmd, capture_output=True, text=True)
    if res_concat.returncode != 0:
        print(f"Concat failed: {res_concat.stderr}")
        return

    final_dur = get_duration(final_out)
    expected_sum = sum(s["dur"] for s in scenes)
    print("=" * 60)
    print(f"Expected Duration (sum of audio): {expected_sum:.2f}s")
    print(f"Final Video Duration: {final_dur:.2f}s")
    print(f"Discrepancy: {abs(final_dur - expected_sum):.3f}s")
    print("=" * 60)

    # ffprobe check of stream durations
    probe = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(final_out)
    ], capture_output=True, text=True)
    meta = json.loads(probe.stdout)
    for st in meta["streams"]:
        print(f"Stream {st['index']} ({st['codec_type']}): codec={st.get('codec_name')}, sample_rate={st.get('sample_rate')}, duration={st.get('duration')}s")

if __name__ == "__main__":
    main()
