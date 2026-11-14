"""Safe aggregate accounting for one model request."""
from collections import Counter

from .schemas import canonical_json

LABELS = {
    "conversation": "Conversation", "workspace": "Artifacts and contributions",
    "methods": "Methods and resources", "instructions": "Instructions and response schema",
    "other": "Other request context",
}
KEYS = {
    **dict.fromkeys(("conversation", "authorText", "authorRequest", "goal"), "conversation"),
    **dict.fromkeys(("artifacts", "authorArtifacts", "contributions", "candidateSource", "source"), "workspace"),
    **dict.fromkeys(("methods", "procedure", "procedures", "resources", "methodContext", "selectedMethods"), "methods"),
}


def wire_messages(request):
    prompt = str(request.get("prompt") or "")
    schema = request.get("schema_json")
    if isinstance(schema, dict):
        prompt += ("\n\nReturn one JSON object with values that conform to the schema below. "
                   "Do not return the schema itself or add fields.\n" + canonical_json(schema))
    return [("system", prompt), ("human", canonical_json(request.get("context") or {}))]


def measure(request, adapter, usage):
    context = request["context"]
    describe = getattr(adapter, "describe_capabilities", lambda: {})()
    configured = bool(getattr(adapter, "configured", False))
    model = describe.get("model") or getattr(adapter, "name", "Unidentified model")
    role = "Decision" if request["node"].startswith("decision.") else "Authoring"
    prompt, body = (text for _, text in wire_messages(request))
    sizes = Counter({"instructions": len(prompt.encode()), "other": len(body.encode())})
    for key, value in context.items():
        label = KEYS.get(key, "other")
        if label != "other":
            size = len(canonical_json({key: value}).encode()) - 2
            sizes[label] += size
            sizes["other"] -= size
    estimate = sum(sizes.values())
    reported = usage.get("input_tokens", usage.get("prompt_tokens"))
    reported = reported if configured and type(reported) is int and reported > 0 else None
    if not (reported or estimate):
        return None
    # A byte-based estimate is intentionally distinct from provider-reported input.
    categories = [{"id": key, "label": label, "tokens": (sizes[key] + 3) // 4}
                  for key, label in LABELS.items() if sizes[key] > 0]
    capacity = describe.get("contextWindow")
    capacity = capacity if type(capacity) is int and capacity > 0 else None
    return {"role": role, "model": model, "demo": bool(getattr(adapter, "demo", False)),
            "source": "reported" if reported is not None else "estimated", "tokens": reported or
            sum(row["tokens"] for row in categories), "capacity": capacity,
            "capacitySource": describe.get("contextWindowSource") if capacity else None,
            "unallocated": reported, "categories": categories}
