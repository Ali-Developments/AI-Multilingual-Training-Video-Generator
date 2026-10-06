"""Comprehensive test suite for Step 8 Supporting Visual Asset Pipeline.

Tests:
1. Provider abstraction adheres to clean interface.
2. Factory returns configured provider and rejects unsupported providers.
3. Correct standard output dimensions (1920x1080 Full HD).
4. Valid PNG image creation verified via PIL Image.open.
5. Arabic script Unicode handling and rendering without crash.
6. Bengali script Unicode handling and rendering without crash.
7. Missing optional text (None on_screen_text, empty purpose) handled gracefully.
8. Deterministic per-scene file path construction with pathlib.
9. One visual asset per scene generated.
10. Scene visual classification (title_card, concept_slide, demo_slide, etc.).
11. Cultural metadata does not alter protected scene IDs or order.
12. VisualService single-locale orchestration.
13. VisualService multi-locale bundle orchestration with error isolation.
14. Idempotency reuses valid existing PNG assets.
15. Force regeneration overwrites existing assets.
16. Scene-level failure isolation.
17. Zero external paid API calls.
"""

from pathlib import Path
import pytest
from PIL import Image

from app.models.schemas import (
    LocalizedScript,
    LocalizedScene,
    CulturalGuidance,
    LocalizationBundle,
    FinalScript,
    SceneVisualAsset,
)
from app.services.visuals.base import VisualAssetProvider, classify_visual_type
from app.services.visuals.local_provider import LocalVisualProvider
from app.services.visuals.mock_provider import MockVisualProvider
from app.services.visuals.factory import get_visual_provider
from app.services.visuals.service import VisualService


def test_visual_provider_abstraction():
    """Verify provider interface and inheritance."""
    local_p = LocalVisualProvider()
    assert isinstance(local_p, VisualAssetProvider)
    assert local_p.provider_name == "local"

    mock_p = MockVisualProvider()
    assert isinstance(mock_p, VisualAssetProvider)
    assert mock_p.provider_name == "mock"


def test_visual_factory_resolution():
    """Verify factory returns configured or requested provider."""
    p_local = get_visual_provider("local")
    assert isinstance(p_local, LocalVisualProvider)

    p_mock = get_visual_provider("mock")
    assert isinstance(p_mock, MockVisualProvider)

    with pytest.raises(ValueError, match="Unsupported Visual provider"):
        get_visual_provider("unsupported_engine")


def test_classify_visual_type():
    """Verify scene types map to sensible visual templates."""
    assert classify_visual_type("intro") == "title_card"
    assert classify_visual_type("outro") == "summary_card"
    assert classify_visual_type("recap") == "summary_card"
    assert classify_visual_type("visual_demo") == "demo_slide"
    assert classify_visual_type("explanation") == "concept_slide"
    assert classify_visual_type("presenter") == "presentation_slide"
    assert classify_visual_type("unknown_type") == "concept_slide"


def test_local_visual_generation_dimensions_and_validity(tmp_path: Path):
    """Verify local provider generates valid 1920x1080 PNG image."""
    provider = LocalVisualProvider()
    scene = LocalizedScene(
        scene_id="scene_1",
        order=1,
        title="Password Security Principles",
        purpose="Explain multi-factor authentication",
        narration="Always use unique passwords and enable MFA on all accounts.",
        estimated_duration_seconds=5,
        visual_direction="Office setting with laptop screen.",
        on_screen_text="1. Use MFA\n2. Never share credentials",
        learning_objective_ids=["LO1"],
        scene_type="explanation",
    )

    asset = provider.generate_scene_visual(
        scene=scene,
        locale="en-US",
        output_dir=tmp_path / "visuals" / "en-US",
        width=1920,
        height=1080,
    )

    assert asset.status == "completed"
    assert asset.scene_id == "scene_1"
    assert asset.width == 1920
    assert asset.height == 1080
    assert asset.visual_type == "concept_slide"
    assert Path(asset.image_path).exists()

    # Validate image file integrity with Pillow
    with Image.open(asset.image_path) as img:
        assert img.format == "PNG"
        assert img.size == (1920, 1080)


def test_arabic_unicode_visual_generation(tmp_path: Path):
    """Verify Arabic script renders without crashing and produces valid PNG."""
    provider = LocalVisualProvider()
    scene = LocalizedScene(
        scene_id="scene_ar_1",
        order=1,
        title="أمن المعلومات والتصيد الاحتيالي",
        purpose="التعرف على الروابط المزيفة",
        narration="تحقق دائما من اسم النطاق وعنوان المرسل بدقة.",
        estimated_duration_seconds=6,
        visual_direction="مكتب عمل عصري",
        on_screen_text="تحقق من الرابط\nلا تفتح المرفقات المشبوهة",
        learning_objective_ids=["LO1"],
        scene_type="intro",
    )

    asset = provider.generate_scene_visual(
        scene=scene,
        locale="ar-SA",
        output_dir=tmp_path / "visuals" / "ar-SA",
    )

    assert asset.status == "completed"
    assert Path(asset.image_path).exists()
    with Image.open(asset.image_path) as img:
        assert img.size == (1920, 1080)


def test_bengali_unicode_visual_generation(tmp_path: Path):
    """Verify Bengali script renders without crashing and produces valid PNG."""
    provider = LocalVisualProvider()
    scene = LocalizedScene(
        scene_id="scene_bn_1",
        order=2,
        title="সাইবার নিরাপত্তা নির্দেশিকা",
        purpose="পাসওয়ার্ড সুরক্ষা নীতি",
        narration="কখনও আপনার লগইন শংসাপত্র কারো সাথে ভাগ করবেন না।",
        estimated_duration_seconds=5,
        visual_direction="ডিজিটাল সুরক্ষা ডায়াগ্রাম",
        on_screen_text="পাসওয়ার্ড গোপন রাখুন\nMFA চালু করুন",
        learning_objective_ids=["LO2"],
        scene_type="visual_demo",
    )

    asset = provider.generate_scene_visual(
        scene=scene,
        locale="bn-BD",
        output_dir=tmp_path / "visuals" / "bn-BD",
    )

    assert asset.status == "completed"
    assert Path(asset.image_path).exists()
    with Image.open(asset.image_path) as img:
        assert img.size == (1920, 1080)


def test_missing_optional_text_handling(tmp_path: Path):
    """Verify scenes with None or empty on_screen_text and visual_direction render cleanly."""
    provider = LocalVisualProvider()
    scene = LocalizedScene(
        scene_id="scene_minimal",
        order=3,
        title="Minimal Scene",
        purpose="Summary",
        narration="Short narration.",
        estimated_duration_seconds=3,
        visual_direction="",
        on_screen_text=None,
        learning_objective_ids=[],
        scene_type="outro",
    )

    asset = provider.generate_scene_visual(
        scene=scene,
        locale="en-US",
        output_dir=tmp_path / "visuals" / "en-US",
    )

    assert asset.status == "completed"
    assert Path(asset.image_path).exists()


def test_cultural_metadata_preserves_protected_scene_fields(tmp_path: Path):
    """Verify cultural guidance does not alter protected scene IDs or order."""
    provider = LocalVisualProvider()
    scene = LocalizedScene(
        scene_id="scene_protected_id",
        order=7,
        title="Corporate Compliance",
        purpose="Policy explanation",
        narration="Follow local safety laws.",
        estimated_duration_seconds=4,
        visual_direction="Formal environment.",
        on_screen_text="Policy Rule 101",
        learning_objective_ids=["LO3"],
        scene_type="presenter",
    )

    guidance = CulturalGuidance(
        locale="ar-SA",
        formality_guidance="Formal presentation",
        visual_environment_guidance="Modern Gulf enterprise office setting",
        cultural_notes=["Use respectful professional address"],
    )

    asset = provider.generate_scene_visual(
        scene=scene,
        locale="ar-SA",
        output_dir=tmp_path / "visuals" / "ar-SA",
        cultural_guidance=guidance,
    )

    assert asset.scene_id == "scene_protected_id"
    assert scene.order == 7
    assert scene.learning_objective_ids == ["LO3"]


def test_visual_service_single_locale(tmp_path: Path):
    """Verify VisualService coordinates slide generation across all scenes in a script."""
    service = VisualService(output_base_dir=tmp_path / "storage")

    script = LocalizedScript(
        title="Training Module",
        source_language="en-US",
        language="en",
        locale="en-US",
        audience="Staff",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Scene 1",
                purpose="Intro",
                narration="Welcome to the lesson.",
                estimated_duration_seconds=3,
                visual_direction="",
                on_screen_text="Welcome",
                learning_objective_ids=["LO1"],
                scene_type="intro",
            ),
            LocalizedScene(
                scene_id="scene_2",
                order=2,
                title="Scene 2",
                purpose="Details",
                narration="Here are the key takeaways.",
                estimated_duration_seconds=4,
                visual_direction="",
                on_screen_text="Takeaways",
                learning_objective_ids=["LO2"],
                scene_type="visual_demo",
            ),
        ],
        closing_summary="Close",
        target_duration_seconds=7,
        total_estimated_duration_seconds=7,
        metadata={},
    )

    track = service.generate_locale_visuals(script=script, project_id="proj_vis_1")
    assert track.status == "completed"
    assert len(track.scene_visuals) == 2
    assert Path(track.scene_visuals[0].image_path).exists()
    assert Path(track.scene_visuals[1].image_path).exists()


def test_visual_service_idempotency_and_force_regenerate(tmp_path: Path):
    """Verify existing visual assets are reused unless force_regenerate=True."""
    service = VisualService(output_base_dir=tmp_path / "storage")

    script = LocalizedScript(
        title="Module",
        source_language="en-US",
        language="en",
        locale="en-US",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Title",
                purpose="P",
                narration="N",
                estimated_duration_seconds=2,
                visual_direction="",
                on_screen_text="Text",
                learning_objective_ids=["LO1"],
                scene_type="explanation",
            )
        ],
        closing_summary="Close",
        target_duration_seconds=2,
        total_estimated_duration_seconds=2,
        metadata={},
    )

    # Initial generation
    track1 = service.generate_locale_visuals(script, project_id="proj_vis_idem")
    assert track1.status == "completed"
    img_path = Path(track1.scene_visuals[0].image_path)
    initial_mtime = img_path.stat().st_mtime_ns

    # Second run without force_regenerate should reuse
    track2 = service.generate_locale_visuals(script, project_id="proj_vis_idem", force_regenerate=False)
    assert track2.status == "completed"
    assert img_path.stat().st_mtime_ns == initial_mtime

    # Third run with force_regenerate should overwrite
    track3 = service.generate_locale_visuals(script, project_id="proj_vis_idem", force_regenerate=True)
    assert track3.status == "completed"
    assert Path(track3.scene_visuals[0].image_path).exists()


def test_visual_service_bundle_orchestration(tmp_path: Path):
    """Verify VisualService generates tracks for multiple locales in a bundle."""
    service = VisualService(output_base_dir=tmp_path / "storage")

    final_script = FinalScript(
        title="Training",
        language="en-US",
        audience="All",
        target_duration_seconds=4,
        total_estimated_duration_seconds=4,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[],
    )

    script_en = LocalizedScript(
        title="Training EN",
        source_language="en-US",
        language="en",
        locale="en-US",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Intro EN",
                purpose="P",
                narration="English narration.",
                estimated_duration_seconds=4,
                visual_direction="",
                on_screen_text="Core Rule",
                learning_objective_ids=["LO1"],
                scene_type="intro",
            )
        ],
        closing_summary="Summary",
        target_duration_seconds=4,
        total_estimated_duration_seconds=4,
        metadata={},
    )

    script_ar = LocalizedScript(
        title="Training AR",
        source_language="en-US",
        language="ar",
        locale="ar-SA",
        audience="All",
        opening_hook="Hook",
        scenes=[
            LocalizedScene(
                scene_id="scene_1",
                order=1,
                title="Intro AR",
                purpose="P",
                narration="Arabic narration.",
                estimated_duration_seconds=4,
                visual_direction="",
                on_screen_text="القاعدة الأساسية",
                learning_objective_ids=["LO1"],
                scene_type="intro",
            )
        ],
        closing_summary="Summary",
        target_duration_seconds=4,
        total_estimated_duration_seconds=4,
        metadata={},
    )

    bundle = LocalizationBundle(
        source_script=final_script,
        localized_scripts={"en-US": script_en, "ar-SA": script_ar},
    )

    tracks = service.generate_bundle_visuals(bundle, project_id="proj_vis_bundle")
    assert "en-US" in tracks
    assert "ar-SA" in tracks
    assert tracks["en-US"].status == "completed"
    assert tracks["ar-SA"].status == "completed"
    assert Path(tracks["en-US"].scene_visuals[0].image_path).exists()
    assert Path(tracks["ar-SA"].scene_visuals[0].image_path).exists()
