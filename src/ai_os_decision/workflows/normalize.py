"""Versioned hashes; graph groups never discard behavior variants."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections import defaultdict

VERSION = "1"


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def validate(workflow: dict) -> list[str]:
    nodes, connections = workflow.get("nodes"), workflow.get("connections")
    if not isinstance(nodes, list) or not isinstance(connections, dict):
        return ["nodes_or_connections_invalid"]
    if not nodes:
        return ["empty_workflow"]
    if len(nodes) > 512:
        return ["node_limit_exceeded"]
    if any(not isinstance(n, dict) or not isinstance(n.get("name"), str) or not isinstance(n.get("type"), str) for n in nodes):
        return ["invalid_node"]
    names = [n["name"] for n in nodes]
    if len(set(names)) != len(names):
        return ["duplicate_node_names"]
    errors = []
    try:
        for name, ports in connections.items():
            if name not in names or not isinstance(ports, dict):
                raise ValueError
            for outputs in ports.values():
                for targets in outputs:
                    for target in targets or []:
                        if target["node"] not in names or not isinstance(target.get("index", 0), int):
                            raise ValueError
    except (TypeError, KeyError, ValueError):
        errors.append("invalid_connection")
    return errors


def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(v) for v in value]
    return type(value).__name__


def _graph(workflow: dict, structural: bool) -> dict:
    nodes = workflow["nodes"]
    indices = {n["name"]: i for i, n in enumerate(nodes)}
    edges = []
    for source, ports in workflow["connections"].items():
        for port, outputs in ports.items():
            for output, targets in enumerate(outputs):
                for t in targets or []:
                    edges.append((indices[source], str(port), output, indices[t["node"]], str(t.get("type", "main")), t.get("index", 0)))
    labels = []
    for node in nodes:
        # Credentials are dependency types, never account identifiers or names.
        item = {"type": node["type"], "version": node.get("typeVersion"), "credentials": sorted(node.get("credentials", {}))}
        params = node.get("parameters", {})
        item["parameters"] = _shape(params) if structural else params
        if not structural:
            item["behavior"] = {k: v for k, v in node.items() if k in {
                "disabled", "alwaysOutputData", "executeOnce", "retryOnFail", "maxTries", "waitBetweenTries", "onError", "continueOnFail"
            }}
        labels.append(item)
    # Partition refinement incorporates directed, typed, indexed edges.
    colors = [digest(x if structural else {**x, "parameters": _shape(x["parameters"])}) for x in labels]
    for _ in range(min(len(nodes), 12)):
        new = [digest([colors[i], sorted((p, out, colors[b], tp, ix) for a, p, out, b, tp, ix in edges if a == i),
                       sorted((colors[a], p, out, tp, ix) for a, p, out, b, tp, ix in edges if b == i)]) for i in range(len(nodes))]
        before = {frozenset(j for j, c in enumerate(colors) if c == col) for col in colors}
        after = {frozenset(j for j, c in enumerate(new) if c == col) for col in new}
        colors = new
        if before == after:
            break
    groups = defaultdict(list)
    for i, color in enumerate(colors):
        groups[color].append(i)
    groups = [groups[c] for c in sorted(groups)]
    count = math.prod(math.factorial(len(g)) for g in groups)
    # Exact canonicalization within color classes. For large symmetric graphs,
    # retain name-based separation rather than risk a false topology merge.
    fallback = count > 720
    orders = ([tuple(sorted(g, key=lambda i: nodes[i]["name"]))] for g in groups) if fallback else (itertools.permutations(g) for g in groups)
    candidates = []
    for grouped in itertools.product(*orders):
        order = list(itertools.chain.from_iterable(grouped))
        mapping = {old: new for new, old in enumerate(order)}
        names = {nodes[i]["name"]: f"node_{mapping[i]}" for i in order}

        def rename(value, names=names):
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rename(v) for v in value]
            if isinstance(value, str):
                # Only documented n8n node-reference syntaxes, not arbitrary text.
                value = re.sub(r"(\$node\[)(['\"])(.*?)\2(\])", lambda m: m[1] + m[2] + names.get(m[3], m[3]) + m[2] + m[4], value)
                return re.sub(r"(\$\()(['\"])(.*?)\2(\))", lambda m: m[1] + m[2] + names.get(m[3], m[3]) + m[2] + m[4], value)
            return value

        value = {"version": VERSION, "nodes": [rename(labels[i]) for i in order],
                 "edges": sorted((mapping[a], p, out, mapping[b], tp, ix) for a, p, out, b, tp, ix in edges)}
        if not structural:
            value["settings"] = workflow.get("settings", {})
        if fallback:
            value["symmetry_names"] = [nodes[i]["name"] for i in order]
        candidates.append(encoded(value))
    return json.loads(min(candidates))


def hashes(workflow: dict, raw: bytes | None = None) -> dict[str, str]:
    errors = validate(workflow)
    if errors:
        raise ValueError(",".join(errors))
    return {"raw_hash": hashlib.sha256(raw if raw is not None else encoded(workflow)).hexdigest(),
            "normalized_hash": digest(_graph(workflow, False)), "structural_hash": digest(_graph(workflow, True))}
