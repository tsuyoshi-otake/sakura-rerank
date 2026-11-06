"""Frozen evaluator payload contracts; provenance truth remains external."""
from __future__ import annotations

import json
import math
import re
from types import MappingProxyType

from .data.contracts import canonical_json_bytes, validate_conversion_candidates
from .current_tiny import HEAD, POLICY, current_factory, native_current_factory, snapshot_policy, validate_policy_facts
from .evaluation_worker import gru_factory, runtime_identity
from . import native_snapshot

SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
REQUIRED_SLICES = frozenset({"reading-short", "reading-multisegment", "context-empty",
    "context-1-63", "context-64", "protected-name", "spelling-policy", "unseen-dictionary"})
LIMIT_BOUNDS = {"startup_seconds": (1, 120), "request_seconds": (.05, 60),
    "model_seconds": (1, 3600), "job_seconds": (1, 14400),
    "metrics_seconds": (1, 3600), "shutdown_seconds": (.1, 10)}


class RunnerError(ValueError):
    """Sanitized contract failure, with no input or model-output fragments."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RunnerError(reason)


def document(raw: bytes) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def constant(_):
        raise RunnerError("nonfinite JSON number")

    def number(value):
        parsed = float(value)
        require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
        require(isinstance(value, dict), "JSON object required")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise RunnerError("invalid evaluator JSON") from None


def fields(value, keys):
    require(isinstance(value, dict) and value.keys() == set(keys), "unexpected evaluator fields")
    return value


def typed_document(raw, kind, keys, *, versions=(1,)):
    value = fields(document(raw), {"kind", "version", *keys})
    require(value["kind"] == kind and type(value["version"]) is int and value["version"] in versions,
            "unsupported evaluator schema")
    return value


def prepare(snapshot, plan_bytes, adapters):
    """Only authenticated non-Test bytes; no model/session or dataset is opened."""
    plan = document(plan_bytes)
    data = plan["data"]
    experiment = typed_document(snapshot[data["experiment"]], "evaluation_execution_plan",
                                 {"runtime", "models", "primary", "comparisons", "slices", "limits"}, versions=(1, 2, 3, 4))
    product = experiment["version"] >= 2
    captured = experiment["version"] >= 3
    full_population = experiment["version"] == 4
    if product:
        policy_factory = native_snapshot.evaluation_policy if captured else snapshot_policy
        expected_policy = policy_factory(plan["artifacts"][data["provenance"]]["sha256"],
                                         **({"full_population":True} if full_population else {}))
        require(canonical_json_bytes(document(snapshot[data["policy"]])) == canonical_json_bytes(expected_policy),
                "native snapshot policy/provenance binding differs")
    require(experiment["runtime"] == runtime_identity(), "runtime differs from the frozen experiment")
    require(experiment["runtime"]["system"] == "Windows", "bounded execution requires Windows")
    require(experiment["runtime"]["packages"]["numpy"] is not None, "metric runtime is unavailable")
    limits = fields(experiment["limits"], LIMIT_BOUNDS)
    for key, (low, high) in LIMIT_BOUNDS.items():
        require(type(limits[key]) in (int, float) and math.isfinite(limits[key]) and low <= limits[key] <= high,
                "execution time bound outside contract")
    slices = experiment["slices"]
    require(isinstance(slices, list) and len(REQUIRED_SLICES) <= len(slices) <= 16
            and all(isinstance(v, str) and NAME.fullmatch(v) for v in slices)
            and len(slices) == len(set(slices)) and REQUIRED_SLICES <= set(slices), "required fixed slices missing")
    sampling = typed_document(snapshot[data["sampling"]], "evaluation_sampling",
        {"test_count", "component_count", "independent_unit", "dependence_evidence_sha256"})
    quality = document(snapshot[data["quality"]])
    require(type(sampling["test_count"]) is int and 3000 <= sampling["test_count"] <= 100_000
            and sampling["test_count"] == quality["valid_test_count"], "sampling and quality counts differ")
    require(type(sampling["component_count"]) is int and 1 <= sampling["component_count"] <= sampling["test_count"],
            "invalid component count")
    require(sampling["independent_unit"] in {"conversion_request", "source_component", "session", "source_author"}
            and isinstance(sampling["dependence_evidence_sha256"], str)
            and SHA.fullmatch(sampling["dependence_evidence_sha256"]), "sampling evidence declaration missing")
    native_commitments = (native_snapshot.validate_provenance(document(snapshot[data["provenance"]]), sampling["test_count"])
                          if captured else None)
    models = experiment["models"]
    require(isinstance(models, list) and len(models) == len(plan["models"]), "model family differs")
    names, run_names, resolved = set(), set(), []
    for spec in models:
        fields(spec, {"model", "adapter", "adapter_identity", "feature_width", "runs"})
        name, adapter_name = spec["model"], spec["adapter"]
        require(isinstance(name, str) and name in plan["models"] and name not in names, "model binding missing or duplicate")
        require(isinstance(adapter_name, str) and adapter_name in adapters, "unsupported evaluation adapter")
        names.add(name)
        adapter = adapters[adapter_name]
        # The current product also uses a GRU, but its protocol-v1 projection
        # omits reading/context and has protected candidate-group selection.
        # Reject this known-incompatible factory regardless of registry alias.
        require(name != "current_tiny" or adapter.factory is not gru_factory,
                "research score adapter does not implement current product policy")
        require(not captured or adapter.factory is not gru_factory,
                "native captures do not establish legacy GRU per-edge features")
        require(adapter.factory is not current_factory or (product and name == "current_tiny"),
                "current product adapter requires the product-policy experiment")
        require(adapter.factory is not current_factory or not full_population,
                "legacy current adapter cannot consume the full native text contract")
        require(adapter.factory is not native_current_factory or (full_population and name == "current_tiny"),
                "native current adapter requires schema4")
        require(adapter.factory not in (current_factory,native_current_factory) or limits["request_seconds"] <= .4,
                "current protocol request deadline widened")
        require(adapter.identity() == spec["adapter_identity"], "adapter identity differs")
        require(type(spec["feature_width"]) is int and 0 <= spec["feature_width"] <= 64, "invalid feature width")
        artifacts = MappingProxyType({role: snapshot[key] for role, key in plan["models"][name].items()})
        try:
            require(adapter.validate(artifacts, spec["feature_width"]) is None, "adapter validator did not accept contract")
        except Exception:
            raise RunnerError("adapter metadata rejected before Test") from None
        configuration = document(artifacts["gate"])["configuration"]
        shipped = product and name == "current_tiny"
        if shipped:
            gate = fields(configuration, {"kind", "source_head"})
            require(gate == {"kind": POLICY, "source_head": HEAD}, "current product policy differs")
            threshold = None
        else:
            gate = fields(configuration, {"kind", "threshold", "operator"})
            require(gate["kind"] == "score_margin" and gate["operator"] == ">"
                    and type(gate["threshold"]) in (int, float) and math.isfinite(gate["threshold"])
                    and 0 <= gate["threshold"] <= 1e6, "unsupported frozen gate")
            threshold = gate["threshold"]
        runs = fields(spec["runs"], {"shipped"} if shipped else {"ungated", "gated"})
        for value in runs.values():
            require(isinstance(value, str) and NAME.fullmatch(value) and value != "baseline" and value not in run_names,
                    "run name missing or duplicate")
            run_names.add(value)
        resolved.append({"spec": spec, "artifacts": artifacts, "adapter": adapter, "threshold": threshold})
    require(names == plan["models"].keys(), "model family incomplete")
    current = next(m["spec"]["runs"]["shipped" if product else "gated"] for m in resolved if m["spec"]["model"] == "current_tiny")
    primary = experiment["primary"]
    require(primary in run_names and primary != current, "primary student run missing")
    pairs = experiment["comparisons"]
    require(isinstance(pairs, list) and 1 <= len(pairs) <= 36, "comparison family outside bound")
    seen = set()
    for pair in pairs:
        require(isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]
                and all(isinstance(v, str) and v in run_names | {"baseline"} for v in pair), "invalid comparison")
        identity = frozenset(pair)
        require(identity not in seen, "duplicate or reversed comparison")
        seen.add(identity)
    require(all([name, "baseline"] in pairs for name in run_names) and [primary, current] in pairs,
            "baseline or current-Tiny comparison missing")
    require(3 + 2 * len(run_names) + len(pairs) <= 64, "comparison family exceeds bootstrap budget")
    return {"plan": plan, "experiment": experiment, "sampling": sampling,
            "quality": quality, "models": resolved, "native_commitments": native_commitments}


def read_cohort(raw, prepared):
    version = prepared["experiment"]["version"]
    value = typed_document(raw, "evaluation_cohort", {"cases"}, versions=(version,))
    rows = value["cases"]
    require(isinstance(rows, list) and len(rows) == prepared["sampling"]["test_count"], "Test population count differs")
    keys, components, normalized, native_identities = set(), set(), [], set()
    for row in rows:
        fields(row, {"case_key", "component_key", "input", "gold", "tags"}
               | ({"product_state"} if version >= 2 else set()) | ({"native_capture"} if version >= 3 else set()))
        require(all(isinstance(row[key], str) and SHA.fullmatch(row[key]) for key in ("case_key", "component_key")),
                "invalid case/component identity")
        require(row["case_key"] not in keys, "duplicate case identity")
        keys.add(row["case_key"])
        components.add(row["component_key"])
        request = fields(row["input"], {"reading", "left_context", "context_policy", "candidates"})
        context = request["left_context"]
        require(isinstance(context, str) and len(context) <= 64
                and request["context_policy"] == "sakura_input_committed_same_session", "untrusted or unbounded context")
        try:
            context.encode("utf-8", errors="strict")
            candidates = (native_snapshot.validate_population_input(request) if version==4
                          else validate_conversion_candidates(request["reading"], request["candidates"]))
        except Exception:
            raise RunnerError("native candidate or text contract invalid") from None
        gold = row["gold"]
        require(isinstance(gold, str) and 1 <= len(gold) <= (native_snapshot.MAX_TEXT_BYTES if version==4 else 256),
                "Gold surface outside bound")
        try:
            gold.encode("utf-8", errors="strict")
            if version==4:
                native_snapshot.validate_native_text(gold)
        except UnicodeError:
            raise RunnerError("invalid Gold text encoding") from None
        tags = row["tags"]
        require(isinstance(tags, list) and all(isinstance(tag, str) for tag in tags)
                and len(set(tags)) == len(tags) and set(tags) <= set(prepared["experiment"]["slices"]),
                "undeclared or duplicate slice tag")
        context_tag = "context-empty" if not context else "context-64" if len(context) == 64 else "context-1-63"
        require(set(tags) & {"context-empty", "context-1-63", "context-64"} == {context_tag}, "context slice differs")
        product_state = ({"product_state": validate_policy_facts(row["product_state"], len(candidates))}
                         if version >= 2 else {})
        if version >= 3:
            require(row["case_key"] in prepared["native_commitments"], "native case commitment missing")
            receipt, identity = native_snapshot.bind_evaluation_case(row, prepared["native_commitments"][row["case_key"]],
                                                                    full_population=version==4)
            require(identity not in native_identities, "native session snapshot replayed")
            native_identities.add(identity)
            product_state["native_binding"] = receipt
        normalized.append({**row, "input": {**request, "candidates": candidates}, **product_state})
    require(len(components) == prepared["sampling"]["component_count"], "component count differs")
    oracle = sum(row["gold"] in [c["surface"] for c in row["input"]["candidates"][:6]] for row in normalized)
    require(oracle == prepared["quality"]["oracle6_present"], "actual oracle differs from quality evidence")
    return normalized
