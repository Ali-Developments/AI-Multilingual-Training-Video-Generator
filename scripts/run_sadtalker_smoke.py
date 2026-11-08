import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Set up project root in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.avatar.sadtalker_provider import SadTalkerProvider
from app.services.tts.audio_probe import get_audio_duration

def main():
    print("=" * 60)
    print("SADTALKER LOCAL SMOKE TEST")
    print("=" * 60)

    audio_path = Path("storage/projects/proj_real_e2e_phishing/audio/ar-SA/scene_1.mp3").resolve()
    image_path = Path("assets/avatars/local_presenter.png").resolve()
    dest_path = Path("storage/projects/proj_real_e2e_phishing/avatars/ar-SA/scene_1_sadtalker.mp4").resolve()

    if not audio_path.exists():
        print(f"ERROR: Audio missing: {audio_path}")
        sys.exit(1)
    if not image_path.exists():
        print(f"ERROR: Image missing: {image_path}")
        sys.exit(1)

    audio_duration = get_audio_duration(audio_path)
    print(f"Input Audio: {audio_path}")
    print(f"Input Audio Duration: {audio_duration:.2f} seconds")
    print(f"Source Portrait: {image_path} ({image_path.stat().st_size} bytes)")
    print(f"Destination: {dest_path}")

    provider = SadTalkerProvider()
    readiness = provider.check_readiness()
    print("\nReadiness check:")
    for k, v in readiness.items():
        print(f"  {k}: {v}")
    
    if not readiness.get("ready"):
        print("ERROR: Provider not ready!")
        sys.exit(1)

    print("\nLaunching SadTalker inference...")
    t0 = time.time()
    job_id = provider.submit_avatar_job(
        scene_id="scene_1",
        locale="ar-SA",
        audio_path=audio_path,
    )
    t1 = time.time()
    inference_time = t1 - t0
    print(f"\nInference completed in {inference_time:.2f} seconds! Job ID: {job_id}")

    job_info = provider.poll_avatar_job(job_id)
    video_url = job_info.get("video_url")
    print(f"Poll result: {job_info}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    provider.download_avatar_video(video_url, dest_path)
    print(f"\nSaved avatar MP4 to: {dest_path}")

    # Inspect with ffprobe
    print("\nRunning ffprobe technical inspection...")
    probe_cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(dest_path),
    ]
    probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
    if probe_res.returncode == 0:
        meta = json.loads(probe_res.stdout)
        video_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), {})
        
        format_info = meta.get("format", {})
        video_duration = float(format_info.get("duration", 0.0))
        drift = abs(video_duration - audio_duration)
        rtf = inference_time / max(video_duration, 0.01)

        print("\n" + "=" * 60)
        print("TECHNICAL VALIDATION METRICS:")
        print("=" * 60)
        print(f"File Exists: {dest_path.exists()}")
        print(f"File Size: {dest_path.stat().st_size} bytes ({dest_path.stat().st_size / 1024 / 1024:.2f} MB)")
        print(f"Width: {video_stream.get('width')}")
        print(f"Height: {video_stream.get('height')}")
        print(f"FPS: {video_stream.get('r_frame_rate')}")
        print(f"Video Codec: {video_stream.get('codec_name')}")
        print(f"Audio Codec: {audio_stream.get('codec_name')}")
        print(f"Input Audio Duration: {audio_duration:.2f}s")
        print(f"Output Video Duration: {video_duration:.2f}s")
        print(f"Duration Drift: {drift:.2f}s")
        print(f"Inference Time: {inference_time:.2f}s")
        print(f"Real-Time Factor (RTF): {rtf:.2f}x")
        print("=" * 60)

        # Save inspection JSON
        report_data = {
            "exists": dest_path.exists(),
            "file_size": dest_path.stat().st_size,
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": video_stream.get("r_frame_rate"),
            "video_codec": video_stream.get("codec_name"),
            "audio_codec": audio_stream.get("codec_name"),
            "input_audio_duration": audio_duration,
            "output_duration": video_duration,
            "duration_drift": drift,
            "inference_time": inference_time,
            "rtf": rtf,
            "device": readiness.get("device", "cuda"),
        }
        with open("storage/projects/proj_real_e2e_phishing/avatars/ar-SA/scene_1_sadtalker_meta.json", "w") as f:
            json.dump(report_data, f, indent=2)
    else:
        print(f"ffprobe failed: {probe_res.stderr}")

if __name__ == "__main__":
    main()
