"""Utilities for transforming Pydantic JSON schemas into Groq / OpenAI strict-mode schemas."""

import copy
from typing import Type, Any, Dict, Union
from pydantic import BaseModel


def to_strict_json_schema(model_or_schema: Union[Type[BaseModel], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Transform a Pydantic model class or JSON Schema dictionary into a strict-mode
    schema compliant with Groq and OpenAI Structured Outputs requirements.

    Strict mode requirements:
    1. Every object schema (root, nested objects, and $defs) MUST have:
       - 'type': 'object'
       - 'additionalProperties': False
       - 'required': list of ALL property names defined in 'properties'
    2. Optional/nullable fields must be represented as nullable types
       (e.g. {'anyOf': [..., {'type': 'null'}]} or {'type': ['...', 'null']}),
       while still being explicitly listed in 'required'.
    3. Unconstrained objects (such as metadata: Dict[str, Any] which have
       additionalProperties=True and no explicit properties) are pruned so
       the strict validator does not reject them.
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

        # If this node represents an object (or defines properties)
        if node.get("type") == "object" or "properties" in node:
            node["type"] = "object"
            node["additionalProperties"] = False
            props = node.get("properties", {})
            if isinstance(props, dict):
                # In strict mode, every property key MUST be present in 'required'
                node["required"] = list(props.keys())
                for p_name, p_schema in props.items():
                    _clean_node(p_schema)

        # Recursively clean array items
        if "items" in node:
            _clean_node(node["items"])

        # Recursively clean anyOf / oneOf / allOf
        for combiner in ("anyOf", "oneOf", "allOf"):
            if combiner in node and isinstance(node[combiner], list):
                for branch in node[combiner]:
                    _clean_node(branch)

    # Process all $defs first
    defs = raw.get("$defs", {})
    if isinstance(defs, dict):
        for def_name, def_schema in defs.items():
            _clean_node(def_schema)

    # Process root schema
    _clean_node(raw)

    # Prune unconstrained dict properties like 'metadata' from properties
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
