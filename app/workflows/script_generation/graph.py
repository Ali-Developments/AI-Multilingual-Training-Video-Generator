"""LangGraph StateGraph construction for the video script generation workflow."""

from typing import Optional
from langgraph.graph import StateGraph, START, END

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.factory import get_llm_provider
from app.workflows.script_generation.state import VideoScriptState
from app.workflows.script_generation.nodes import ScriptWorkflowNodes


def route_after_normalize(state: VideoScriptState) -> str:
    """Route after input normalization."""
    if state.workflow_status == "failed":
        return END
    return "analyze_content"


def route_after_analyze(state: VideoScriptState) -> str:
    """Route after content analysis."""
    if state.workflow_status == "failed":
        return END
    return "generate_script"


def route_after_generate(state: VideoScriptState) -> str:
    """Route after initial script generation."""
    if state.workflow_status == "failed":
        return END
    return "validate_script"


def route_after_validation(state: VideoScriptState) -> str:
    """
    Evaluate validation results and determine next workflow step:
    - If valid: finalize
    - If invalid and under revision limit: revise
    - If invalid and revision limit reached: mark_needs_review
    """
    if state.workflow_status == "failed":
        return END

    if state.validation and state.validation.is_valid:
        return "finalize_script"

    if state.revision_count < state.max_revisions:
        return "revise_script"

    return "mark_needs_review"


def create_script_workflow(llm_provider: Optional[LLMProvider] = None):
    """
    Build and compile the deterministic LangGraph script generation workflow.
    
    Args:
        llm_provider: Injected LLM provider interface. Defaults to application factory.
    """
    provider = llm_provider or get_llm_provider()
    nodes = ScriptWorkflowNodes(llm_provider=provider)

    workflow = StateGraph(VideoScriptState)

    # Register workflow nodes
    workflow.add_node("normalize_input", nodes.normalize_input)
    workflow.add_node("analyze_content", nodes.analyze_content)
    workflow.add_node("generate_script", nodes.generate_script)
    workflow.add_node("validate_script", nodes.validate_script)
    workflow.add_node("revise_script", nodes.revise_script)
    workflow.add_node("finalize_script", nodes.finalize_script)
    workflow.add_node("mark_needs_review", nodes.mark_needs_review)

    # Connect workflow edges
    workflow.add_edge(START, "normalize_input")
    workflow.add_conditional_edges(
        "normalize_input",
        route_after_normalize,
        ["analyze_content", END]
    )
    workflow.add_conditional_edges(
        "analyze_content",
        route_after_analyze,
        ["generate_script", END]
    )
    workflow.add_conditional_edges(
        "generate_script",
        route_after_generate,
        ["validate_script", END]
    )
    workflow.add_conditional_edges(
        "validate_script",
        route_after_validation,
        ["finalize_script", "revise_script", "mark_needs_review", END]
    )
    workflow.add_edge("revise_script", "validate_script")
    workflow.add_edge("finalize_script", END)
    workflow.add_edge("mark_needs_review", END)

    return workflow.compile()
