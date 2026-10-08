"""Streamlit Frontend Application for AI Training Video Generation Platform.

Provides an interactive dashboard for:
- Inputting training video requirements (topic, content, locales, duration, audience, tone).
- Inspecting canonical and localized scripts (with RTL/LTR and cultural notes).
- Audio waveform tracks and playback.
- Avatar video segments and eligibility.
- Supporting visual slide graphics and subtitle cues (SRT/VTT).
- Composed final multilingual training videos with preview and download.
- Manifest lifecycle tracking, idempotency, and partial pipeline resume.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

from frontend.helpers import (
    DEFAULT_BACKEND_URL,
    DIRECT_ENGINE_AVAILABLE,
    APIClientError,
    check_backend_health,
    create_project_via_api,
    fetch_project_manifest_via_api,
    fetch_projects_direct,
    fetch_projects_via_api,
    format_api_error_detail,
    load_manifest_direct,
    resume_project_via_api,
    run_project_via_api,
    serialize_create_project_payload,
)

try:
    from app.core.config import settings
    from app.models.schemas import TrainingVideoRequest
    from app.workflows.orchestrator import ProjectOrchestrator
except ImportError:
    settings = None
    TrainingVideoRequest = None
    ProjectOrchestrator = None

logger = logging.getLogger(__name__)

def render_app():
    """Main Streamlit UI renderer."""
    st.set_page_config(
        page_title="AI Multilingual Training Video Studio",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ---------------------------------------------------------------------------
    # Sidebar UI: Mode, Providers & Project Selector
    # ---------------------------------------------------------------------------

    with st.sidebar:
        st.title("⚙️ Video Studio")
        st.caption("Multilingual AI Video Orchestration")

        # Engine Connection Mode
        st.subheader("Connection Mode")
        backend_url = st.text_input("FastAPI Backend URL", value=DEFAULT_BACKEND_URL)
        health = check_backend_health(backend_url)

        if health:
            st.success("🟢 Backend Connected (API Mode)")
            api_mode = True
        else:
            st.warning("🟡 Backend Offline — Direct Mode Active")
            api_mode = False

        st.markdown("---")
        st.subheader("Select Project")

        # Load project list
        if api_mode:
            project_list = fetch_projects_via_api(backend_url)
        else:
            project_list = fetch_projects_direct()

        project_options = {p["project_id"]: f"{p['project_id'][:8]} — {p.get('topic', 'Untitled')[:25]}" for p in project_list}

        selected_project_id = st.selectbox(
            "Current Active Project",
            options=list(project_options.keys()),
            format_func=lambda x: project_options.get(x, x),
            index=0 if project_options else None,
        )

        # Load active project manifest early for provider inspection
        active_manifest: Optional[Dict[str, Any]] = None
        if selected_project_id:
            if api_mode:
                active_manifest = fetch_project_manifest_via_api(backend_url, selected_project_id)
            else:
                active_manifest = load_manifest_direct(selected_project_id)

        if st.button("🔄 Refresh Projects"):
            st.rerun()

        st.markdown("---")
        st.subheader("Provider Status")

        # Dynamic Provider Badges
        health_details = health.get("details", {}) if health else {}
        if health:
            llm_provider_name = health_details.get("llm_provider") or health_details.get("default_llm", "groq")
            llm_model_name = health_details.get("llm_model", "openai/gpt-oss-20b")
            tts_engine_name = health_details.get("default_tts", "edge_tts")
            avatar_engine_name = health_details.get("default_avatar", "mock")
            live_heygen_gate = health_details.get("enable_live_heygen", False)
        elif settings:
            llm_provider_name = settings.DEFAULT_LLM_PROVIDER
            llm_model_name = settings.GROQ_MODEL if settings.DEFAULT_LLM_PROVIDER == "groq" else settings.DEFAULT_LLM_PROVIDER
            tts_engine_name = settings.DEFAULT_TTS_PROVIDER
            avatar_engine_name = settings.DEFAULT_AVATAR_PROVIDER
            live_heygen_gate = getattr(settings, "ENABLE_LIVE_HEYGEN", False)
        else:
            llm_provider_name = "Unavailable"
            llm_model_name = "Unavailable"
            tts_engine_name = "Unavailable"
            avatar_engine_name = "Unavailable"
            live_heygen_gate = False

        if llm_provider_name == "Unavailable":
            st.markdown("- **LLM Provider:** `Unavailable`")
            st.markdown("- **TTS Engine:** `Unavailable`")
            st.markdown("- **Default Avatar Provider:** `Unavailable`")
        else:
            st.markdown(f"- **LLM Provider:** `{llm_provider_name.capitalize()} ({llm_model_name})`")
            st.markdown(f"- **TTS Engine:** `{tts_engine_name.replace('_', '-').capitalize()} (Local Free Tier)`")
            st.markdown(f"- **Default Avatar Provider:** `{avatar_engine_name}`")
            if active_manifest:
                proj_avatar = active_manifest.get("avatar_provider") or active_manifest.get("source_request", {}).get("avatar_provider", "mock")
                st.markdown(f"- **Current Project Avatar Provider:** `{proj_avatar}`")
            else:
                st.markdown("- **Current Project Avatar Provider:** `None selected`")

        st.markdown("- **Visual Engine:** `Local Visuals (Pillow Full HD)`")
        st.markdown("- **Compositor:** `FFmpeg Local Native Engine`")

    # ---------------------------------------------------------------------------
    # Main Tabs UI
    # ---------------------------------------------------------------------------

    tab_create, tab_script, tab_media, tab_visuals, tab_composed, tab_manifest = st.tabs([
        "🚀 New Project",
        "📜 Scripts & Locales",
        "🎙️ Audio & 👤 Avatars",
        "🖼️ Visuals & 💬 Subtitles",
        "🎬 Final Composed Videos",
        "📋 Project Manifest",
    ])

    # ---------------------------------------------------------------------------
    # TAB 1: New Project Creation & Execution
    # ---------------------------------------------------------------------------
    with tab_create:
        st.header("Create & Launch Training Video Project")
        st.markdown(
            "Define your instructional requirements. The orchestrator will generate canonical scripts, "
            "localize into target languages, synthesize voiceovers, prepare avatars and slide graphics, "
            "and compose final videos with FFmpeg."
        )

        with st.form("project_creation_form"):
            col_left, col_right = st.columns(2)

            with col_left:
                topic_input = st.text_input(
                    "Training Topic *",
                    value="Workplace Phishing Defense Essentials",
                    help="The core subject matter or instructional title.",
                )
                source_content_input = st.text_area(
                    "Source Content / Reference Notes (Optional)",
                    value="Phishing emails often mimic IT department urgent password reset requests. Always inspect the sender domain, avoid clicking links in unsolicited messages, and report suspicious emails to the security operations center immediately.",
                    height=120,
                    help="Raw reference documentation or lesson curriculum.",
                )
                audience_input = st.text_input(
                    "Target Audience",
                    value="Corporate Employees",
                    help="Who this video is designed to train.",
                )
                learning_objectives_input = st.text_area(
                    "Learning Objectives (One per line)",
                    value="Recognize deceptive sender email addresses\nVerify password reset links safely\nReport suspicious communications to IT security",
                    height=90,
                )

            with col_right:
                base_lang_input = st.selectbox(
                    "Source / Base Language",
                    options=["en-US", "ar-SA", "bn-BD", "es-ES", "fr-FR"],
                    index=0,
                    help="Language of the source content. Must match the language of your topic / source text.",
                )
                target_locales_input = st.multiselect(
                    "Target Locales *",
                    options=["ar-SA", "bn-BD", "es-ES", "fr-FR", "de-DE", "zh-CN"],
                    default=["ar-SA"],
                    help="Select target multilingual locales to produce video packages for.",
                )
                target_duration_input = st.slider(
                    "Target Duration (seconds) *",
                    min_value=30,
                    max_value=300,
                    value=30,
                    step=10,
                    help="Target runtime for the composed training video.",
                )
                col_tone, col_diff = st.columns(2)
                with col_tone:
                    tone_input = st.selectbox(
                        "Tone",
                        options=["professional", "authoritative", "encouraging", "conversational"],
                        index=0,
                    )
                with col_diff:
                    difficulty_input = st.selectbox(
                        "Difficulty",
                        options=["beginner", "intermediate", "advanced"],
                        index=0,
                    )

                st.markdown("---")
                avatar_choice = st.selectbox(
                    "Avatar Engine Mode",
                    options=[
                        "SadTalker Local — Free",
                        "Mock",
                        "HeyGen Live — Paid",
                    ],
                    index=0,
                    help="SadTalker runs locally for free without external API credits. Mock generates local safe placeholders. HeyGen Live connects to external paid cloud API.",
                )
                ack_paid_credits = False
                if "SadTalker" in avatar_choice:
                    avatar_provider = "sadtalker"
                    st.info("ℹ️ **SadTalker Local:** Runs locally. No API credits required.")
                    portrait_path_input = st.text_input(
                        "Local Presenter Portrait Path",
                        value="assets/avatars/local_presenter.png",
                        help="Path to source portrait image used by SadTalker.",
                    )
                elif "HeyGen" in avatar_choice:
                    avatar_provider = "heygen"
                    st.warning("⚠️ **Credit Warning:** External paid API. May consume credits.")
                    ack_paid_credits = st.checkbox(
                        "I acknowledge and confirm that this action will consume paid HeyGen credits.",
                        value=False,
                    )
                else:
                    avatar_provider = "mock"

                force_regenerate = st.checkbox("Force Regenerate (Overwrite existing assets)", value=False)

            submit_btn = st.form_submit_button("🎬 Create & Generate Full Video Package", use_container_width=True)

        if submit_btn:
            from app.core.language import validate_source_language_mismatch
            source_check_text = (source_content_input or topic_input or "").strip()
            lang_mismatch = validate_source_language_mismatch(source_check_text, base_lang_input)

            if not topic_input and not source_content_input:
                st.error("Please provide at least a Topic or Source Content.")
            elif lang_mismatch:
                st.error(f"⚠️ **Language Mismatch Detected:** {lang_mismatch}")
            elif not target_locales_input:
                st.error("Please select at least one Target Locale.")
            elif avatar_provider == "heygen" and not ack_paid_credits:
                st.error("⚠️ You must check the acknowledgement box to proceed with paid HeyGen Live rendering.")
            else:
                objectives = [line.strip() for line in learning_objectives_input.split("\n") if line.strip()]
                payload = serialize_create_project_payload(
                    topic=topic_input,
                    source_content=source_content_input or None,
                    audience=audience_input,
                    base_language=base_lang_input,
                    target_languages=target_locales_input,
                    target_duration_seconds=target_duration_input,
                    tone=tone_input,
                    difficulty_level=difficulty_input,
                    learning_objectives=objectives,
                    avatar_provider=avatar_provider,
                    ack_paid_credits=ack_paid_credits,
                )

                with st.spinner("Initializing and executing autonomous video pipeline..."):
                    if api_mode:
                        try:
                            create_res = create_project_via_api(backend_url, payload, raise_for_status=True)
                            if create_res:
                                new_pid = create_res["project_id"]
                                st.info(f"Project initialized: `{new_pid}`. Running pipeline...")
                                run_res = run_project_via_api(backend_url, new_pid, force_regenerate=force_regenerate)
                                if run_res:
                                    p_status = run_res.get("status", "unknown")
                                    if p_status == "completed":
                                        st.success(f"🎉 Pipeline completed successfully with status: {p_status}!")
                                    elif p_status == "needs_review":
                                        st.warning(f"⚠️ Pipeline completed with status: {p_status}. Review required.")
                                    elif p_status == "failed":
                                        st.error(f"❌ Pipeline failed with status: {p_status}. Inspect diagnostics below.")
                                    else:
                                        st.info(f"ℹ️ Pipeline executed with status: {p_status}.")
                                    st.rerun()
                                else:
                                    st.error("Pipeline execution failed to start or complete.")
                        except APIClientError as api_err:
                            st.error(f"❌ Project creation failed (HTTP {api_err.status_code}): {api_err.message}")
                            st.markdown(format_api_error_detail(api_err.detail))
                            if api_err.detail:
                                with st.expander("🔍 View Technical Server Response", expanded=False):
                                    st.json({"status_code": api_err.status_code, "detail": api_err.detail})
                        except Exception as exc:
                            st.error(f"❌ Unexpected error connecting to API: {exc}")
                    elif DIRECT_ENGINE_AVAILABLE and ProjectOrchestrator and TrainingVideoRequest:
                        try:
                            req = TrainingVideoRequest(**payload["request"])
                            orchestrator = ProjectOrchestrator()
                            manifest = orchestrator.create_project(req)
                            st.info(f"Project initialized directly: `{manifest.project_id}`. Running pipeline...")
                            result_manifest = orchestrator.run_pipeline(manifest.project_id, force_regenerate=force_regenerate)
                            if result_manifest.status == "completed":
                                st.success(f"🎉 Pipeline finished directly with status: {result_manifest.status}!")
                            elif result_manifest.status == "needs_review":
                                st.warning(f"⚠️ Pipeline finished with status: {result_manifest.status}. Review required.")
                            elif result_manifest.status == "failed":
                                st.error(f"❌ Pipeline failed directly with status: {result_manifest.status}.")
                            else:
                                st.info(f"ℹ️ Pipeline finished with status: {result_manifest.status}.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Direct pipeline run error: {exc}")
                    else:
                        st.error("Neither backend API nor direct engine is accessible.")

    # ---------------------------------------------------------------------------
    # Project View State
    # ---------------------------------------------------------------------------
    if not active_manifest:
        with tab_script:
            st.info("No project selected or manifest empty. Create or select a project in the sidebar.")
        with tab_media:
            st.info("No project selected or manifest empty.")
        with tab_visuals:
            st.info("No project selected or manifest empty.")
        with tab_composed:
            st.info("No project selected or manifest empty.")
        with tab_manifest:
            st.info("No project selected or manifest empty.")
    else:
        # -----------------------------------------------------------------------
        # TAB 2: Scripts & Locales
        # -----------------------------------------------------------------------
        with tab_script:
            st.header(f"Scripts & Localization — Project `{selected_project_id[:8]}`")
            status_col1, status_col2, status_col3 = st.columns(3)
            with status_col1:
                st.metric("Overall Status", active_manifest.get("status", "unknown").upper())
            with status_col2:
                st.metric("Script Status", active_manifest.get("script_status", "unknown").upper())
            with status_col3:
                st.metric("Localization Status", active_manifest.get("localization_status", "unknown").upper())

            # Canonical Source Script (mapping final_script or source_script)
            source_script = active_manifest.get("final_script") or active_manifest.get("source_script")
            if not source_script and active_manifest.get("localization_bundle"):
                source_script = active_manifest["localization_bundle"].get("source_script")
            
            if source_script:
                st.subheader("Canonical Source Script (English / Base)")
                st.markdown(
                    f"**Title:** {source_script.get('title', 'N/A')} | "
                    f"**Target Duration:** {source_script.get('target_duration_seconds', 0)}s | "
                    f"**Estimated Duration:** {source_script.get('estimated_duration_seconds', 0)}s"
                )
                
                scenes = source_script.get("scenes", [])
                for sc in scenes:
                    with st.expander(f"Scene {sc.get('scene_id')}: {sc.get('scene_type', 'generic').upper()} ({sc.get('estimated_duration_seconds', 0)}s)", expanded=False):
                        st.markdown(f"**Narration:** {sc.get('narration')}")
                        st.markdown(f"**Visual Direction:** {sc.get('visual_direction')}")
                        st.markdown(f"**On-Screen Text:** {sc.get('on_screen_text') or '*None*'}")
                        if sc.get("learning_objective_ids"):
                            st.caption(f"Objectives: {', '.join(sc.get('learning_objective_ids', []))}")
            else:
                st.warning("Canonical source script not yet generated.")

            # Localized Scripts (mapping localization_bundle.localized_scripts)
            loc_bundle = active_manifest.get("localization_bundle")
            localized_scripts = {}
            if loc_bundle:
                localized_scripts = loc_bundle.get("localized_scripts") or loc_bundle.get("scripts") or {}

            if localized_scripts:
                st.markdown("---")
                st.subheader("Localized Multilingual Scripts")
                loc_tabs = st.tabs(list(localized_scripts.keys()))
                for ltab, (loc_code, loc_sc) in zip(loc_tabs, localized_scripts.items()):
                    with ltab:
                        dir_badge = "➡️ LTR" if loc_sc.get("text_direction") == "ltr" else "⬅️ RTL"
                        dur = loc_sc.get("total_estimated_duration_seconds") or loc_sc.get("estimated_duration_seconds", 0)
                        st.markdown(f"**Locale:** `{loc_code}` | **Direction:** {dir_badge} | **Duration:** {dur}s")
                        
                        cg = loc_sc.get("cultural_guidance") or loc_sc.get("cultural_adaptations")
                        if cg:
                            with st.info("Cultural Guidance & Notes"):
                                if isinstance(cg, dict):
                                    for k, v in cg.items():
                                        if v:
                                            st.markdown(f"- **{k.replace('_', ' ').capitalize()}:** {v}")
                                elif isinstance(cg, list):
                                    for item in cg:
                                        st.markdown(f"- {item}")

                        for sc in loc_sc.get("scenes", []):
                            with st.expander(f"Scene {sc.get('scene_id')}: {sc.get('scene_type', 'scene').upper()} ({sc.get('estimated_duration_seconds', 0)}s)", expanded=False):
                                st.markdown(f"**Localized Narration:** {sc.get('narration')}")
                                st.markdown(f"**Visual Direction:** {sc.get('visual_direction')}")
                                st.markdown(f"**On-Screen Text:** {sc.get('on_screen_text') or '*None*'}")

        # -----------------------------------------------------------------------
        # TAB 3: Audio & Avatars
        # -----------------------------------------------------------------------
        with tab_media:
            st.header("Audio Tracks & Avatar Video Segments")
            audio_bundle = active_manifest.get("audio_tracks", {})
            avatar_bundle = active_manifest.get("avatar_tracks", {})

            col_audio, col_avatar = st.columns(2)

            with col_audio:
                st.subheader("🎙️ Synthesized Speech (Edge-TTS)")
                if not audio_bundle:
                    st.info("Audio tracks not synthesized yet.")
                else:
                    for loc_code, track in audio_bundle.items():
                        total_dur = track.get("total_audio_duration_seconds", track.get("total_duration_seconds", 0.0))
                        track_meta = track.get("metadata", {})
                        scene_audio_list = track.get("scene_audio", track.get("scene_audios", []))
                        
                        voice_id = track.get("voice_id") or track_meta.get("voice_id")
                        provider = track.get("provider") or track_meta.get("provider")
                        if not voice_id and scene_audio_list:
                            voice_id = scene_audio_list[0].get("voice_id")
                        if not provider and scene_audio_list:
                            provider = scene_audio_list[0].get("provider")

                        with st.expander(f"Locale `{loc_code}` — Total: {total_dur:.2f}s", expanded=True):
                            st.caption(f"Voice ID: `{voice_id or 'N/A'}` | Provider: `{provider or 'N/A'}`")
                            for sc_audio in scene_audio_list:
                                st.markdown(f"**Scene {sc_audio.get('scene_id')}** ({sc_audio.get('duration_seconds', 0.0):.2f}s):")
                                audio_path = sc_audio.get("audio_path")
                                if audio_path and Path(audio_path).is_file():
                                    st.audio(audio_path)
                                else:
                                    st.caption(f"File: `{audio_path}`")

            with col_avatar:
                st.subheader("👤 Talking Avatar Segments")
                proj_avatar_provider = active_manifest.get("avatar_provider") or active_manifest.get("source_request", {}).get("avatar_provider", "mock")
                st.caption(f"Selected Avatar Provider: `{proj_avatar_provider}`")

                if not avatar_bundle:
                    st.info("Avatar video segments not generated yet.")
                else:
                    for loc_code, av_track in avatar_bundle.items():
                        track_provider = av_track.get("metadata", {}).get("provider", proj_avatar_provider)
                        scene_avatars = av_track.get("scene_avatars", av_track.get("avatar_videos", []))

                        with st.expander(f"Locale `{loc_code}` Avatar Segments (Provider: {track_provider})", expanded=True):
                            if not scene_avatars:
                                st.caption("No scene avatars found in track.")
                            for av_asset in scene_avatars:
                                sc_id = av_asset.get("scene_id")
                                sc_status = av_asset.get("status", "unknown")
                                sc_dur = av_asset.get("duration_seconds", 0.0)
                                vpath = av_asset.get("video_path")
                                err = av_asset.get("error")

                                eligibility = "Ineligible / Skipped" if sc_status == "skipped" else "Eligible (Avatar Rendered)"
                                st.markdown(f"**Scene {sc_id}** — Status: `{sc_status.upper()}` | `{eligibility}` | Duration: `{sc_dur:.2f}s`")

                                if err:
                                    st.error(f"Error: {err}")

                                if vpath and Path(vpath).is_file():
                                    st.video(vpath)
                                elif vpath:
                                    st.caption(f"Asset Path: `{vpath}`")

            # -------------------------------------------------------------------
            # Post-TTS Duration Reconciliation UI
            # -------------------------------------------------------------------
            duration_rec_meta = active_manifest.get("metadata", {}).get("duration_reconciliation", {})
            if duration_rec_meta:
                st.markdown("---")
                st.subheader("⏱️ Post-TTS Duration Reconciliation & Timing Ground Truth")
                for loc_code, rec_data in duration_rec_meta.items():
                    with st.expander(f"Locale `{loc_code}` Duration Reconciliation State", expanded=True):
                        d_col1, d_col2, d_col3, d_col4 = st.columns(4)
                        with d_col1:
                            st.metric("Requested Target", f"{rec_data.get('target_duration_seconds', 0.0):.1f}s")
                        with d_col2:
                            st.metric("Initial TTS Audio", f"{rec_data.get('initial_duration_seconds', 0.0):.1f}s")
                        with d_col3:
                            st.metric("Final Approved Audio", f"{rec_data.get('final_duration_seconds', 0.0):.1f}s")
                        with d_col4:
                            st.metric("Status", rec_data.get("status", "unknown").upper())

                        history = rec_data.get("history", [])
                        if history:
                            st.markdown("#### Revision Iterations")
                            for h in history:
                                st.markdown(
                                    f"- **Revision {h.get('revision_number')}:** Before={h.get('measured_duration_before', 0.0):.2f}s "
                                    f"| Ratio={h.get('compression_ratio', 1.0):.3f} "
                                    f"| After={h.get('measured_duration_after', 0.0):.2f}s "
                                    f"| Delta=±{h.get('delta_seconds', 0.0):.2f}s"
                                )
                        st.caption(rec_data.get("message", ""))

        # -----------------------------------------------------------------------
        # TAB 4: Visuals & Subtitles
        # -----------------------------------------------------------------------
        with tab_visuals:
            st.header("Visual Slide Graphics & Subtitles")
            vis_bundle = active_manifest.get("visual_tracks", {})
            sub_bundle = active_manifest.get("subtitle_tracks", {})

            vcol, scol = st.columns(2)

            with vcol:
                st.subheader("🖼️ Full HD Visual Slide Cards (1920x1080)")
                if not vis_bundle:
                    st.info("Visual slide assets not generated yet.")
                else:
                    for loc_code, vtrack in vis_bundle.items():
                        st.markdown(f"**Locale `{loc_code}` Visual Assets:**")
                        scene_visuals = vtrack.get("scene_visuals", vtrack.get("visual_assets", []))
                        if not scene_visuals:
                            st.caption("No visual assets in track.")
                        for vis in scene_visuals:
                            img_path = vis.get("image_path")
                            headline = vis.get("headline", "")
                            caption = f"Scene {vis.get('scene_id')} | Layout: {vis.get('visual_type')} | Status: {vis.get('status', 'completed')}"
                            if headline:
                                caption += f" | {headline}"
                            if img_path and Path(img_path).is_file():
                                st.image(img_path, caption=caption, use_container_width=True)
                            else:
                                st.caption(f"Scene {vis.get('scene_id')}: `{img_path}`")

            with scol:
                st.subheader("💬 Subtitle Tracks (SRT & VTT)")
                if not sub_bundle:
                    st.info("Subtitles not generated yet.")
                else:
                    for loc_code, strack in sub_bundle.items():
                        with st.expander(f"Locale `{loc_code}` Subtitle Files", expanded=True):
                            srt_path = strack.get("srt_path")
                            vtt_path = strack.get("vtt_path")
                            if srt_path and Path(srt_path).is_file():
                                content = Path(srt_path).read_text(encoding="utf-8")
                                st.markdown(f"**SRT File (`{Path(srt_path).name}`):**")
                                st.code(content[:800] + ("..." if len(content) > 800 else ""), language="text")
                                st.download_button(
                                    f"⬇️ Download {loc_code} SRT",
                                    data=content,
                                    file_name=f"{loc_code}.srt",
                                    mime="text/plain",
                                    key=f"dl_srt_{loc_code}",
                                )
                            if vtt_path and Path(vtt_path).is_file():
                                vtt_content = Path(vtt_path).read_text(encoding="utf-8")
                                st.download_button(
                                    f"⬇️ Download {loc_code} VTT",
                                    data=vtt_content,
                                    file_name=f"{loc_code}.vtt",
                                    mime="text/vtt",
                                    key=f"dl_vtt_{loc_code}",
                                )

        # -----------------------------------------------------------------------
        # TAB 5: Composed Final Videos
        # -----------------------------------------------------------------------
        with tab_composed:
            st.header("🎬 Final Composed Training Videos")
            final_videos = active_manifest.get("final_videos", {})
            if not final_videos and active_manifest.get("composition_track"):
                final_videos = active_manifest["composition_track"].get("final_videos", {})
            
            if not final_videos:
                st.info("Final video composition has not been completed yet.")
            else:
                for loc_code, fvid in final_videos.items():
                    st.subheader(f"Video Package: `{loc_code}`")
                    c1, c2 = st.columns([3, 2])
                    vpath = fvid.get("video_path")
                    scene_videos = fvid.get("scene_videos", [])
                    total_scenes = fvid.get("scene_count", len(scene_videos))
                    avatar_scenes_success = sum(1 for sc in scene_videos if sc.get("has_avatar"))

                    avatar_track = active_manifest.get("avatar_tracks", {}).get(loc_code, {})
                    eligible_avatar_count = sum(
                        1 for sc in avatar_track.get("scene_avatars", [])
                        if sc.get("status") != "skipped"
                    ) or avatar_scenes_success
                    
                    with c1:
                        if vpath and Path(vpath).is_file():
                            st.video(vpath)
                            with open(vpath, "rb") as vf:
                                vbytes = vf.read()
                            st.download_button(
                                label=f"⬇️ Download {loc_code} Training Video (MP4)",
                                data=vbytes,
                                file_name=f"training_{loc_code}.mp4",
                                mime="video/mp4",
                                key=f"dl_video_{loc_code}",
                                use_container_width=True,
                            )
                        else:
                            st.warning(f"Video file not found at path: `{vpath}`")

                    with c2:
                        st.markdown("### 📊 Composition Details")
                        st.markdown(f"- **Locale:** `{fvid.get('locale', loc_code)}`")
                        dur = fvid.get("total_duration_seconds", fvid.get("duration_seconds", 0.0))
                        st.markdown(f"- **Duration:** `{dur:.2f} seconds`")
                        res = fvid.get("metadata", {}).get("resolution") or fvid.get("resolution", "1920x1080")
                        fps = fvid.get("metadata", {}).get("fps") or fvid.get("fps", 25)
                        comp_provider = fvid.get("metadata", {}).get("provider") or "ffmpeg"
                        proj_provider = active_manifest.get("avatar_provider", "mock")
                        st.markdown(f"- **Resolution:** `{res}` Full HD")
                        st.markdown(f"- **Framerate:** `{fps} FPS`")
                        st.markdown(f"- **Compositor Engine:** `{comp_provider}`")
                        st.markdown(f"- **Avatar Engine:** `{proj_provider}`")
                        st.markdown(f"- **Scene Count:** `{total_scenes} scenes`")
                        st.markdown(f"- **Final Video Path:** `{vpath}`")

                        if eligible_avatar_count > 0:
                            if avatar_scenes_success == eligible_avatar_count:
                                st.success(f"✅ **Avatar scenes:** {avatar_scenes_success}/{eligible_avatar_count} successful")
                            else:
                                st.error(f"❌ **Avatar scenes:** {avatar_scenes_success}/{eligible_avatar_count} successful (Failure State)")
                        else:
                            st.info("ℹ️ **Avatar scenes:** 0/0 (Visual only)")

        # -----------------------------------------------------------------------
        # TAB 6: Manifest & Project Operations
        # -----------------------------------------------------------------------
        with tab_manifest:
            st.header("📋 Project Manifest & Pipeline Actions")
            
            col_act1, col_act2, col_act3 = st.columns(3)
            with col_act1:
                if st.button("▶️ Run Pipeline (Idempotent)", use_container_width=True):
                    with st.spinner("Executing pipeline..."):
                        if api_mode:
                            run_res = run_project_via_api(backend_url, selected_project_id, force_regenerate=False)
                        elif DIRECT_ENGINE_AVAILABLE and ProjectOrchestrator:
                            orchestrator = ProjectOrchestrator()
                            run_res = orchestrator.run_pipeline(selected_project_id, force_regenerate=False)
                        st.success("Pipeline executed!")
                        st.rerun()

            with col_act2:
                if st.button("🔁 Resume Pipeline", use_container_width=True):
                    with st.spinner("Resuming pipeline..."):
                        if api_mode:
                            res_res = resume_project_via_api(backend_url, selected_project_id)
                        elif DIRECT_ENGINE_AVAILABLE and ProjectOrchestrator:
                            orchestrator = ProjectOrchestrator()
                            res_res = orchestrator.resume_pipeline(selected_project_id)
                        st.success("Pipeline resumed!")
                        st.rerun()

            with col_act3:
                if st.button("⚡ Force Regenerate All Assets", use_container_width=True):
                    with st.spinner("Force regenerating all pipeline stages..."):
                        if api_mode:
                            run_res = run_project_via_api(backend_url, selected_project_id, force_regenerate=True)
                        elif DIRECT_ENGINE_AVAILABLE and ProjectOrchestrator:
                            orchestrator = ProjectOrchestrator()
                            run_res = orchestrator.run_pipeline(selected_project_id, force_regenerate=True)
                        st.success("Force regeneration completed!")
                        st.rerun()

            st.markdown("---")
            st.subheader("Raw `project.json` Manifest")
            st.json(active_manifest)


if __name__ == "__main__" or "streamlit" in __name__:
    render_app()
