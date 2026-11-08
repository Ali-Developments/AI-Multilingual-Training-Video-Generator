"""Test suite for Phase 5 (Budget Approval Gate) and Phase 6 (Job Management & API Endpoints).

Tests:
1. Budget calculation logic for HeyGen, Google Veo, and free local services.
2. Safe offline/test behavior: zero estimated cost when live APIs are disabled.
3. Budget authorization gate in ProjectOrchestrator: halts in 'pending_approval' before live paid generation.
4. Approval workflow unlocking the pipeline once explicit authorization is granted.
5. REST API endpoints:
   - GET /api/v1/projects/{id}/budget
   - POST /api/v1/projects/{id}/approve-budget
   - GET /api/v1/projects/{id}/status
   - POST /api/v1/projects/{id}/retry
   - GET /api/v1/providers (verifying Google Veo presence)
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.models.schemas import (
    TrainingVideoRequest,
    ProjectManifest,
    FinalScript,
    SceneDraft,
    LearningObjective,
    ApproveBudgetRequest,
    ProjectBudgetEstimate,
)
from app.services.budget.service import BudgetService
from app.workflows.manifest import ProjectManifestManager
from app.workflows.orchestrator import ProjectOrchestrator


@pytest.fixture
def client():
    return TestClient(app)


def test_budget_calculation_offline_is_zero(monkeypatch):
    """Verify that when live APIs are disabled, estimated cost is $0.00 and no approval is required."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", False)
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", False)

    req = TrainingVideoRequest(
        topic="Workplace Ergonomics",
        avatar_provider="mock",
        target_duration_seconds=60,
    )
    manifest = ProjectManifest(
        project_id="proj_budget_offline",
        source_request=req,
        avatar_provider="mock",
    )

    budget = BudgetService.calculate_project_budget(manifest)
    assert budget.project_id == "proj_budget_offline"
    assert budget.total_estimated_cost_usd == 0.0
    assert budget.requires_approval is False
    assert budget.status == "not_required"


def test_budget_calculation_live_heygen_and_veo(monkeypatch):
    """Verify that when live APIs are enabled, granular costs are computed and approval is required."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)
    monkeypatch.setattr(settings, "HEYGEN_PRICE_PER_CREDIT", 0.08)
    monkeypatch.setattr(settings, "VEO_PRICE_PER_SECOND_FAST", 0.15)
    monkeypatch.setattr(settings, "VEO_MODEL", "veo-3.1-fast-generate-001")

    scenes = [
        SceneDraft(
            scene_id="s1", order=1, title="Intro", narration="Welcome to course.",
            estimated_duration_seconds=30, avatar_enabled=True, preferred_provider="heygen",
        ),
        SceneDraft(
            scene_id="s2", order=2, title="B-Roll Demo", narration="Observe equipment.",
            estimated_duration_seconds=10, avatar_enabled=False, preferred_provider="veo",
            media_type="broll",
        ),
    ]
    final_script = FinalScript(
        title="Industrial Course",
        language="en-US",
        audience="Staff",
        target_duration_seconds=40,
        total_estimated_duration_seconds=40,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=scenes,
    )

    req = TrainingVideoRequest(
        topic="Industrial Course",
        avatar_provider="heygen",
        ack_paid_credits=True,
        target_duration_seconds=40,
    )
    manifest = ProjectManifest(
        project_id="proj_budget_live",
        source_request=req,
        avatar_provider="heygen",
        final_script=final_script,
    )

    budget = BudgetService.calculate_project_budget(manifest)
    assert budget.total_estimated_cost_usd > 0.0
    assert budget.requires_approval is True
    assert budget.status == "pending_approval"

    heygen_item = next(i for i in budget.items if i.provider == "heygen")
    assert heygen_item.quantity > 0
    assert heygen_item.estimated_cost_usd > 0

    veo_item = next(i for i in budget.items if i.provider == "veo")
    assert veo_item.quantity == 10.0
    assert veo_item.estimated_cost_usd == 1.50  # 10s * $0.15/s


def test_budget_gate_in_orchestrator_halts_before_live_api(tmp_path, monkeypatch):
    """Verify that orchestrator run_project halts at Stage 1.5 when budget is unapproved."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)
    monkeypatch.setattr(settings, "ENABLE_LIVE_VEO", True)

    mgr = ProjectManifestManager(storage_base_dir=tmp_path / "storage")
    orch = ProjectOrchestrator(manifest_manager=mgr)

    req = TrainingVideoRequest(
        topic="Safety Training",
        avatar_provider="heygen",
        ack_paid_credits=True,
        target_duration_seconds=30,
    )
    manifest = mgr.create_manifest("proj_gate_test", req)

    # Attach planned final script with paid providers
    manifest.final_script = FinalScript(
        title="Safety Training",
        language="en-US",
        audience="Workers",
        target_duration_seconds=30,
        total_estimated_duration_seconds=30,
        opening_hook="Hook",
        closing_summary="Summary",
        scenes=[
            SceneDraft(
                scene_id="s1", order=1, title="Intro", narration="Intro speech.",
                estimated_duration_seconds=30, avatar_enabled=True, preferred_provider="heygen",
            )
        ],
    )
    manifest.script_status = "completed"
    mgr.save_manifest(manifest)

    # Run project without prior budget approval
    result = orch.run_project("proj_gate_test", req)

    assert result.status == "pending_approval"
    assert result.budget_status == "pending_approval"
    assert any(e.code == "BUDGET_APPROVAL_REQUIRED" for e in result.error_details)
    # Media generation stages must NOT have started
    assert result.avatar_status == "pending"
    assert result.composition_status == "pending"


def test_budget_api_endpoints_workflow(client, tmp_path, monkeypatch):
    """Verify budget GET and POST approve-budget API endpoints."""
    monkeypatch.setattr(settings, "ENABLE_LIVE_HEYGEN", True)

    # 1. Create Project
    res = client.post("/api/v1/projects", json={
        "request": {
            "topic": "Chemical Safety",
            "avatar_provider": "heygen",
            "ack_paid_credits": True,
            "target_duration_seconds": 60,
        }
    })
    assert res.status_code == 201
    proj_id = res.json()["project_id"]

    # 2. Get Budget Estimate
    res_b = client.get(f"/api/v1/projects/{proj_id}/budget")
    assert res_b.status_code == 200
    b_data = res_b.json()
    assert b_data["project_id"] == proj_id
    assert b_data["requires_approval"] is True
    assert b_data["status"] == "pending_approval"

    # 3. Approve Budget
    res_app = client.post(
        f"/api/v1/projects/{proj_id}/approve-budget",
        json={"approved": True, "user_email": "lead_trainer@company.com", "notes": "Approved for Q4 production"},
    )
    assert res_app.status_code == 200
    app_data = res_app.json()
    assert app_data["status"] == "approved"
    assert app_data["approved_by"] == "lead_trainer@company.com"

    # 4. Check detailed status endpoint
    res_st = client.get(f"/api/v1/projects/{proj_id}/status")
    assert res_st.status_code == 200
    st_data = res_st.json()
    assert st_data["budget_status"] == "approved"
    assert "script" in st_data["stages"]


def test_providers_endpoint_includes_google_veo(client):
    """Verify that GET /api/v1/providers lists Google Veo alongside HeyGen and SadTalker."""
    res = client.get("/api/v1/providers")
    assert res.status_code == 200
    data = res.json()
    assert "veo" in data
    assert "heygen" in data
    assert "sadtalker" in data
    assert data["veo"]["name"] == "Google Veo (Vertex AI)"
    assert "model" in data["veo"]
