"""Utilities for transforming Pydantic JSON schemas, generating concrete instance templates,
and validating that LLM responses are real data instances rather than echoed JSON Schemas or placeholders."""

import copy
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel


def to_strict_json_schema(model_or_schema: Union[Type[BaseModel], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Transform a Pydantic model class or JSON Schema dictionary into a strict-mode
    schema compliant with Groq and OpenAI Structured Outputs requirements.
    """
    if isinstance(model_or_schema, dict):
        raw = copy.deepcopy(model_or_schema)
    elif hasattr(model_or_schema, "model_json_schema"):
        raw = copy.deepcopy(model_or_schema.model_json_schema())
    else:
        raise TypeError(f"Expected BaseModel subclass or dict, got {type(model_or_schema)}")

    def _clean_node(node: Any) -> None:
        if not isinstance(node, dict):
            return

        if node.get("type") == "object" or "properties" in node:
            node["type"] = "object"
            node["additionalProperties"] = False
            props = node.get("properties", {})
            if isinstance(props, dict):
                node["required"] = list(props.keys())
                for p_name, p_schema in props.items():
                    _clean_node(p_schema)

        if "items" in node:
            _clean_node(node["items"])

        for combiner in ("anyOf", "oneOf", "allOf"):
            if combiner in node and isinstance(node[combiner], list):
                for branch in node[combiner]:
                    _clean_node(branch)

    defs = raw.get("$defs", {})
    if isinstance(defs, dict):
        for def_name, def_schema in defs.items():
            _clean_node(def_schema)

    _clean_node(raw)

    if "properties" in raw and isinstance(raw["properties"], dict):
        keys_to_prune = []
        for prop_name, prop_val in raw["properties"].items():
            if isinstance(prop_val, dict) and prop_val.get("type") == "object" and not prop_val.get("properties"):
                keys_to_prune.append(prop_name)
        for k in keys_to_prune:
            del raw["properties"][k]
            if "required" in raw and k in raw["required"]:
                raw["required"].remove(k)

    return raw


def to_compact_json_schema_str(model_or_schema: Union[Type[BaseModel], Dict[str, Any]]) -> str:
    """
    Serialize a Pydantic JSON schema into a token-efficient minified JSON string
    by stripping verbose 'description' and 'title' metadata fields.
    """
    strict = to_strict_json_schema(model_or_schema)

    def _strip_verbose_meta(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("description", None)
            node.pop("title", None)
            for val in node.values():
                _strip_verbose_meta(val)
        elif isinstance(node, list):
            for item in node:
                _strip_verbose_meta(item)

    _strip_verbose_meta(strict)
    return json.dumps(strict, separators=(",", ":"), ensure_ascii=False)


def build_json_instance_template(schema: Type[BaseModel]) -> str:
    """
    Build a clean, concrete JSON instance template (WITHOUT '$defs', 'properties',
    'additionalProperties', or 'type': 'object' meta-schema wrappers) so that models
    in prompt/json_object mode produce a real data instance instead of echoing a JSON Schema.
    """
    name = getattr(schema, "__name__", "")

    if name == "ContentAnalysis":
        template = {
            "topic_summary": "Concise executive summary of the training topic in the required canonical language",
            "key_concepts": ["Concept 1", "Concept 2"],
            "learning_objectives": [
                {
                    "id": "LO1",
                    "description": "Concrete, measurable learning outcome in the required canonical language",
                },
                {
                    "id": "LO2",
                    "description": "Second learning outcome in the required canonical language",
                },
            ],
            "audience_notes": "Pedagogical notes tailored to the target audience",
            "recommended_scene_count": 4,
            "recommended_structure": ["Introduction", "Core Demonstration", "Practical Steps", "Summary"],
            "important_terms": ["Term 1", "Term 2"],
            "factual_constraints": ["Constraint 1"],
        }
        return json.dumps(template, indent=2, ensure_ascii=False)

    if name == "ScriptDraft":
        template = {
            "title": "Complete training module title in the required canonical language",
            "language": "ar-SA",
            "audience": "Target learner profile",
            "opening_hook": "Engaging opening hook sentence in the required canonical language",
            "closing_summary": "Key takeaways and closing summary in the required canonical language",
            "learning_objectives": [
                {
                    "id": "LO1",
                    "description": "Learning objective description in the required canonical language",
                }
            ],
            "scenes": [
                {
                    "scene_id": "scene_1",
                    "order": 1,
                    "title": "Scene title in the required canonical language",
                    "purpose": "Instructional purpose of this scene",
                    "scene_type": "presenter",
                    "narration": "Full spoken presenter narration paragraph for this scene in the required canonical language",
                    "visual_direction": "Concrete visual description for this scene",
                    "motion_description": "Camera or subject movement description",
                    "camera_movement": "static",
                    "on_screen_text": "Short overlay text or null",
                    "learning_objective_ids": ["LO1"],
                    "estimated_duration_seconds": 15,
                }
            ],
            "total_estimated_duration_seconds": 60,
        }
        return json.dumps(template, indent=2, ensure_ascii=False)

    if name == "LocalizedScript":
        template = {
            "title": "Localized script title in target locale",
            "source_language": "en-US",
            "language": "ar-SA",
            "locale": "ar-SA",
            "text_direction": "rtl",
            "audience": "Target audience",
            "learning_objectives": [
                {"id": "LO1", "description": "Localized objective description"}
            ],
            "opening_hook": "Localized opening hook",
            "closing_summary": "Localized closing summary",
            "target_duration_seconds": 60,
            "total_estimated_duration_seconds": 60,
            "scenes": [
                {
                    "scene_id": "scene_1",
                    "order": 1,
                    "title": "Localized scene title",
                    "purpose": "Localized scene purpose",
                    "scene_type": "presenter",
                    "narration": "Complete localized spoken narration for this scene",
                    "estimated_duration_seconds": 15,
                    "visual_direction": "Localized visual direction",
                    "on_screen_text": "Localized overlay text or null",
                    "learning_objective_ids": ["LO1"],
                }
            ],
        }
        return json.dumps(template, indent=2, ensure_ascii=False)

    if name == "ScriptOutline":
        template = {
            "title": "Complete training module title in the required canonical language",
            "language": "ar-SA",
            "audience": "Target learner profile in the required canonical language",
            "opening_hook": "Engaging opening hook sentence in the required canonical language",
            "closing_summary": "Key takeaways and closing summary in the required canonical language",
            "learning_objectives": [
                {
                    "id": "LO1",
                    "description": "Learning objective description in the required canonical language",
                }
            ],
            "scene_outlines": [
                {
                    "scene_id": "scene_1",
                    "order": 1,
                    "title": "Scene 1 title in the required canonical language",
                    "purpose": "Brief summary of what this scene teaches",
                    "scene_type": "intro",
                    "learning_objective_ids": ["LO1"],
                    "target_duration_seconds": 10,
                }
            ],
        }
        return json.dumps(template, indent=2, ensure_ascii=False)

    if name == "SceneDraft":
        template = {
            "scene_id": "scene_1",
            "order": 1,
            "title": "Scene title in the required canonical language",
            "purpose": "Instructional role of this scene in the required canonical language",
            "scene_type": "presenter",
            "narration": "Complete spoken presenter narration for this scene in the required canonical language",
            "visual_direction": "Concrete visual guidance for footage, graphics, or actions in the required canonical language",
            "motion_description": "Camera or subject movement description",
            "camera_movement": "static",
            "on_screen_text": "Short overlay text in the required canonical language",
            "learning_objective_ids": ["LO1"],
            "estimated_duration_seconds": 15,
        }
        return json.dumps(template, indent=2, ensure_ascii=False)

    # Generic fallback for arbitrary Pydantic models: build a sample dict from model_fields
    sample: Dict[str, Any] = {}
    model_fields = getattr(schema, "model_fields", {})
    for f_name, f_info in model_fields.items():
        annotation_str = str(getattr(f_info, "annotation", "str")).lower()
        if "int" in annotation_str:
            sample[f_name] = 1
        elif "float" in annotation_str:
            sample[f_name] = 1.0
        elif "bool" in annotation_str:
            sample[f_name] = True
        elif "list" in annotation_str:
            sample[f_name] = []
        elif "dict" in annotation_str:
            sample[f_name] = {}
        else:
            sample[f_name] = f"<{f_name}>"
    return json.dumps(sample, indent=2, ensure_ascii=False)


def is_json_schema_echo(
    raw_or_parsed: Union[str, Dict[str, Any]],
    target_schema: Optional[Type[BaseModel]] = None,
) -> bool:
    """
    Detect whether the LLM returned a JSON Schema definition (e.g., containing '$defs',
    'properties', 'additionalProperties', or field type descriptors) instead of an
    actual data instance of `target_schema`.
    """
    model_fields = set(getattr(target_schema, "model_fields", {}).keys()) if target_schema else set()

    if isinstance(raw_or_parsed, str):
        text = raw_or_parsed.strip()
        try:
            return is_json_schema_echo(json.loads(text), target_schema)
        except (ValueError, TypeError):
            pass
        if '"$defs"' in text or '"$schema"' in text:
            return True
        if '"properties"' in text and '"additionalProperties"' in text and "properties" not in model_fields:
            return True
        return False

    if isinstance(raw_or_parsed, dict):
        keys = set(raw_or_parsed.keys())
        if "$defs" in keys or "$schema" in keys:
            return True
        if "properties" in keys and "properties" not in model_fields:
            if "type" in keys or "required" in keys or "additionalProperties" in keys:
                return True
        if "type" in keys and not keys.issubset(model_fields) and keys <= {"$defs", "properties", "required", "type", "title", "description", "additionalProperties"}:
            return True

        # Check if multiple top-level field values are JSON Schema property descriptors like {"type": "string"}
        schema_descriptor_count = 0
        for k, v in raw_or_parsed.items():
            if k in model_fields and isinstance(v, dict):
                v_keys = set(v.keys())
                if "type" in v_keys and v_keys <= {"type", "title", "description", "default", "items", "anyOf", "$ref", "enum", "minimum", "maximum"}:
                    schema_descriptor_count += 1
        if schema_descriptor_count >= 2:
            return True

    return False


def contains_placeholder_syntax(
    raw_text: str,
    parsed_data: Optional[Dict[str, Any]] = None,
    target_schema: Optional[Type[BaseModel]] = None,
) -> Optional[str]:
    """
    Check whether raw JSON text or parsed dictionary contains invalid placeholder syntax
    such as `{...}`, `[...]`, unquoted `...`, or placeholder strings in required content fields.

    Returns a descriptive error string if placeholders are found, or None if clean.
    """
    if not raw_text or not raw_text.strip():
        return "Model returned an empty response."

    # 1. Unquoted ellipses inside JSON braces/brackets or after colons: `{...}`, `[...]`, `: ...`
    outside_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', raw_text)
    if re.search(r"\{\s*\.\.\.\s*\}|\[\s*\.\.\.\s*\]|:\s*\.\.\.\s*[,}\]]", outside_strings):
        return (
            "Output contains abbreviated placeholder ellipses ('{...}' or '[...]') instead of "
            "complete JSON values. Every object and array must be fully expanded with real data."
        )

    if parsed_data is not None and isinstance(parsed_data, dict):
        schema_name = getattr(target_schema, "__name__", "")
        placeholder_Tokens = {"...", "…", "{...}", "[...]", "todo", "tbd", "<string>", "null"}
        def has_marker(value: Any) -> bool:
            if isinstance(value, list):
                return any(has_marker(item) for item in value)
            if isinstance(value, dict):
                return any(has_marker(item) for item in value.values())
            return isinstance(value, str) and value.strip().lower() in placeholder_Tokens

        if has_marker(parsed_data):
            return "Output contains a placeholder instead of a completed value."

        if schema_name == "ScriptDraft":
            title = str(parsed_data.get("title") or "").strip()
            if not title or title.lower() in placeholder_Tokens or title.startswith("Complete training module title"):
                return "ScriptDraft 'title' is missing or contains a template placeholder instead of a real title."

            scenes = parsed_data.get("scenes")
            if not isinstance(scenes, list) or len(scenes) == 0:
                return "ScriptDraft 'scenes' must be a non-empty list of scene objects."

            for idx, sc in enumerate(scenes, start=1):
                if not isinstance(sc, dict):
                    return f"Scene {idx} in 'scenes' must be a JSON object, got {type(sc).__name__}."
                narration = str(sc.get("narration") or "").strip()
                sc_title = str(sc.get("title") or "").strip()
                if not narration or narration.lower() in placeholder_Tokens or narration.startswith("Full spoken presenter narration"):
                    return f"Scene {idx} is missing real spoken 'narration' text."
                if not sc_title or sc_title.lower() in placeholder_Tokens:
                    return f"Scene {idx} is missing a real scene 'title'."

        elif schema_name == "ScriptOutline":
            title = str(parsed_data.get("title") or "").strip()
            if not title or title.lower() in placeholder_Tokens or title.startswith("Complete training module title"):
                return "ScriptOutline 'title' is missing or contains a template placeholder instead of a real title."
            outlines = parsed_data.get("scene_outlines")
            if not isinstance(outlines, list) or len(outlines) == 0:
                return "ScriptOutline 'scene_outlines' must be a non-empty list of scene outline objects."
            for idx, item in enumerate(outlines, start=1):
                if not isinstance(item, dict):
                    return f"Scene outline {idx} must be a JSON object."
                sc_title = str(item.get("title") or "").strip()
                if not sc_title or sc_title.lower() in placeholder_Tokens or sc_title.startswith("Scene 1 title"):
                    return f"Scene outline {idx} is missing a real 'title'."

        elif schema_name == "SceneDraft":
            sc_title = str(parsed_data.get("title") or "").strip()
            narration = str(parsed_data.get("narration") or "").strip()
            if not sc_title or sc_title.lower() in placeholder_Tokens or sc_title.startswith("Scene title in the required"):
                return "SceneDraft 'title' is missing or contains a template placeholder."
            if not narration or narration.lower() in placeholder_Tokens or narration.startswith("Complete spoken presenter narration"):
                return "SceneDraft 'narration' is missing or contains a template placeholder."

        elif schema_name == "ContentAnalysis":
            summary = str(parsed_data.get("topic_summary") or "").strip()
            if not summary or summary.lower() in placeholder_Tokens or summary.startswith("Concise executive summary"):
                return "ContentAnalysis 'topic_summary' is missing or contains a template placeholder."
            los = parsed_data.get("learning_objectives")
            if not isinstance(los, list) or len(los) == 0:
                return "ContentAnalysis 'learning_objectives' must be a non-empty list."

    return None


def _extract_balanced_json_objects(text: str) -> List[str]:
    """Extract all top-level balanced `{...}` substrings from text, respecting quoted strings."""
    candidates: List[str] = []
    depth = 0
    start_idx = -1
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"' and depth:
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx != -1:
                    candidates.append(text[start_idx : i + 1].strip())
                    start_idx = -1

    return candidates


def extract_json_payload(raw_text: str, target_schema: Optional[Type[BaseModel]] = None) -> str:
    """
    Extract a clean JSON object string from an LLM response that may include
    <think>...</think> reasoning blocks, markdown ```json fences, or surrounding prose.

    If multiple `{...}` blocks exist in the response (e.g., the model mentioned a schema
    snippet first and then output the real JSON instance), prefers the real instance over
    schema echoes or `{...}` placeholders.
    """
    if not raw_text:
        return ""

    text = raw_text.strip()
    # Strip <think>...</think> reasoning tags produced by reasoning models
    while text.lower().startswith("<think>"):
        end = text.lower().find("</think>")
        if end < 0:
            return ""
        text = text[end + len("</think>"):].strip()
    if text.startswith(("{", "[")):
        try:
            json.loads(text)
            return text
        except ValueError:
            pass

    # 1. Collect fenced ```json ... ``` blocks first
    fenced_matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    balanced_objects = _extract_balanced_json_objects(text)

    # Filter out bare "{...}" mentions from prose when a real JSON object starting with `{"` exists later
    real_json_start_match = re.search(r'\{\s*"[a-zA-Z_]', text)
    trailing_unclosed: Optional[str] = None
    if real_json_start_match:
        tail_candidate = text[real_json_start_match.start() :].strip()
        if tail_candidate.count("{") > tail_candidate.count("}"):
            trailing_unclosed = tail_candidate

    all_candidates = [c.strip() for c in (fenced_matches + balanced_objects) if c and c.strip()]
    if not all_candidates:
        if trailing_unclosed:
            return trailing_unclosed
        first_brace = text.find("{")
        if first_brace != -1:
            return text[first_brace:].strip()
        return text

    # Prefer a candidate that parses cleanly as JSON, is NOT a schema echo, and has no placeholder ellipses
    for cand in reversed(all_candidates):
        if is_json_schema_echo(cand, target_schema):
            continue
        if contains_placeholder_syntax(cand, target_schema=target_schema) is not None:
            continue
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict) and not is_json_schema_echo(parsed, target_schema):
                if target_schema is not None:
                    target_schema.model_validate(parsed)
                return cand
        except Exception:
            continue

    # If the only balanced candidates were prose mentions like `{...}` and there is a trailing unclosed JSON object,
    # return the trailing unclosed JSON object so truncation is accurately diagnosed.
    if trailing_unclosed and all(c == "{...}" for c in all_candidates):
        return trailing_unclosed

    # Second pass: any candidate that is not a schema echo and not bare "{...}"
    for cand in all_candidates:
        if cand != "{...}" and not is_json_schema_echo(cand, target_schema):
            return cand

    return all_candidates[-1]


def validate_structured_instance(
    raw_text: str,
    schema: Type[BaseModel],
) -> BaseModel:
    """
    Validate raw LLM output into a Pydantic `schema` instance, rejecting:
    1. JSON Schema definitions (`$defs`, `properties`, `additionalProperties`)
    2. Placeholder ellipses (`{...}`, `[...]`, `...`)
    3. Truncated or malformed JSON
    4. Missing required fields or template placeholders
    """
    cleaned = extract_json_payload(raw_text, target_schema=schema)
    if not cleaned:
        raise ValueError(f"Empty JSON payload extracted for {schema.__name__}.")

    if is_json_schema_echo(cleaned, target_schema=schema):
        raise ValueError(
            f"Model returned a JSON Schema definition ('$defs'/'properties') instead of an actual {schema.__name__} data instance. "
            f"Do NOT output the schema definition; output a concrete JSON object populated with real {schema.__name__} values."
        )

    placeholder_err = contains_placeholder_syntax(cleaned, target_schema=schema)
    if placeholder_err:
        raise ValueError(placeholder_err)

    try:
        parsed_data = json.loads(cleaned)
    except json.JSONDecodeError as dec_err:
        # Check if truncated mid-stream (unbalanced braces/brackets)
        if not cleaned.startswith("{"):
            raise ValueError(f"No final JSON object supplied for {schema.__name__}.") from dec_err
        if dec_err.pos >= len(cleaned.rstrip()) or dec_err.msg.startswith("Unterminated string"):
            raise ValueError(
                f"Truncated JSON output for {schema.__name__} (unclosed braces/brackets at end of response): {dec_err}"
            ) from dec_err
        raise ValueError(f"Invalid JSON syntax for {schema.__name__}: {dec_err}") from dec_err

    if not isinstance(parsed_data, dict):
        raise ValueError(f"Expected a JSON object for {schema.__name__}, got {type(parsed_data).__name__}.")

    if is_json_schema_echo(parsed_data, target_schema=schema):
        raise ValueError(
            f"Model returned a JSON Schema definition ('$defs'/'properties') instead of an actual {schema.__name__} data instance."
        )

    semantic_err = contains_placeholder_syntax(cleaned, parsed_data=parsed_data, target_schema=schema)
    if semantic_err:
        raise ValueError(semantic_err)

    return schema.model_validate(parsed_data)


def compact_messages_for_token_limit(
    messages: list[Dict[str, str]],
    max_chars_per_message: int = 3200,
) -> list[Dict[str, str]]:
    """
    Deterministically compact a list of chat messages after an HTTP 413 oversized
    request error so that a bounded retry never re-sends the identical oversized payload.
    """
    compacted: list[Dict[str, str]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "") or ""
        squeezed = re.sub(r"\n{3,}", "\n\n", content)
        squeezed = re.sub(r"[ \t]{2,}", " ", squeezed).strip()
        if len(squeezed) > max_chars_per_message:
            head_len = int(max_chars_per_message * 0.65)
            tail_len = max_chars_per_message - head_len - 40
            squeezed = (
                squeezed[:head_len]
                + "\n...[compacted for token budget]...\n"
                + squeezed[-tail_len:]
            )
        compacted.append({"role": role, "content": squeezed})
    return compacted
