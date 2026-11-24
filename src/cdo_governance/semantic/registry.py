"""Strict, versioned and recursive CDO definition registry.

Contracts are business metadata, NOT physical dbt models. Definitions can select
attributes and metrics from another versioned contract. Nothing is silently
inherited: selections are explicit and cycles/missing references fail closed.
"""
from copy import deepcopy
from pathlib import Path
import re

import yaml

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CONCEPT = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
METRIC_KEYS = {"name", "description", "type", "agg", "expr", "fill_nulls_with"}
AGGREGATIONS = {"sum", "count", "average", "min", "max", "count_distinct"}


def _definition_files(path):
    path = Path(path)
    if path.is_dir():
        files = sorted(path.rglob("*.yml")) + sorted(path.rglob("*.yaml"))
    elif path.is_file():
        files = [path]
    else:
        files = []
    if not files:
        raise ValueError(f"No CDO definition files at {path}")
    return files


def _validate_attributes(attributes, context):
    if not isinstance(attributes, list) or not attributes:
        raise ValueError(f"{context}: expected non-empty attributes")
    seen = set()
    for attr in attributes:
        if not isinstance(attr, dict) or set(attr) != {"name", "data_type", "description"}:
            raise ValueError(f"{context}: attributes must have name, data_type, description only")
        name = attr["name"]
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ValueError(f"{context}: invalid attribute name")
        if name in seen:
            raise ValueError(f"{context}: duplicate attribute {name}")
        seen.add(name)
        if not isinstance(attr["data_type"], str) or not attr["data_type"].strip():
            raise ValueError(f"{context}: attribute {name} requires data_type")
        if not isinstance(attr["description"], str):
            raise ValueError(f"{context}: attribute {name} requires description")


def _validate_metrics(metrics, attributes, context):
    if not isinstance(metrics, list):
        raise ValueError(f"{context}: metrics must be a list")
    seen = set()
    allowed = {a["name"] for a in attributes}
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) - METRIC_KEYS:
            raise ValueError(f"{context}: invalid flat metric declaration")
        name = metric.get("name")
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ValueError(f"{context}: invalid metric name")
        if name in seen:
            raise ValueError(f"{context}: duplicate metric {name}")
        seen.add(name)
        if metric.get("type") != "simple":
            raise ValueError(f"{context}: only simple metrics are supported")
        if metric.get("agg") not in AGGREGATIONS:
            raise ValueError(f"{context}: invalid aggregation for {name}")
        if metric.get("expr") not in allowed:
            raise ValueError(f"{context}: metric {name} references a non-standard column")
        if "description" in metric and not isinstance(metric["description"], str):
            raise ValueError(f"{context}: invalid metric description {name}")


def _selected_names(values, context, required=False):
    if not isinstance(values, list) or (required and not values):
        raise ValueError(f"{context}: expected {'non-empty ' if required else ''}list")
    if any(not isinstance(name, str) or not IDENTIFIER.fullmatch(name) for name in values):
        raise ValueError(f"{context}: names must be identifiers")
    if len(set(values)) != len(values):
        raise ValueError(f"{context}: duplicate selections")
    return values


def load_registry(path):
    """Return fully resolved contracts keyed by (concept name, string version).

    Standalone complete contracts remain valid for backwards-compatible tests.
    Registry entrypoints should pass the *directory*, not a single leaf file.
    """
    raw = {}
    for file in _definition_files(path):
        obj = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError(f"{file}: expected YAML mapping")
        name, version = obj.get("name"), obj.get("version")
        if not isinstance(name, str) or not CONCEPT.fullmatch(name):
            raise ValueError(f"{file}: invalid contract name")
        if type(version) is not int or version < 1:
            raise ValueError(f"{file}: version must be a positive integer")
        key = (name, str(version))
        if key in raw:
            raise ValueError(f"{file}: duplicate CDO contract {name} v{version}")
        raw[key] = (obj, str(file))

    resolved = {}
    visiting = []

    def resolve(key):
        if key in resolved:
            return resolved[key]
        if key in visiting:
            chain = " -> ".join(f"{n}@{v}" for n, v in visiting + [key])
            raise ValueError(f"Circular CDO inheritance: {chain}")
        if key not in raw:
            raise ValueError(f"Missing CDO parent/version: {key}")
        spec, location = raw[key]
        visiting.append(key)
        try:
            if "uses" in spec or "uses_version" in spec or "include" in spec:
                if set(spec) != {"name", "version", "uses", "uses_version", "include"}:
                    raise ValueError(f"{location}: invalid inherited-contract structure")
                parent_name, parent_version = spec["uses"], spec["uses_version"]
                if not isinstance(parent_name, str) or type(parent_version) is not int:
                    raise ValueError(f"{location}: invalid parent reference")
                parent = resolve((parent_name, str(parent_version)))
                incl = spec["include"]
                if not isinstance(incl, dict) or set(incl) != {"attributes", "metrics"}:
                    raise ValueError(f"{location}: include requires attributes and metrics lists")
                requested_attrs = _selected_names(incl["attributes"], f"{location} attributes", True)
                requested_metrics = _selected_names(incl["metrics"], f"{location} metrics")
                available_attrs = {a["name"]: a for a in parent["attributes"]}
                available_metrics = {m["name"]: m for m in parent["metrics"]}
                if set(requested_attrs) - set(available_attrs):
                    raise ValueError(f"{location}: unknown inherited attributes {sorted(set(requested_attrs) - set(available_attrs))}")
                if set(requested_metrics) - set(available_metrics):
                    raise ValueError(f"{location}: unknown inherited metrics {sorted(set(requested_metrics) - set(available_metrics))}")
                attrs = [deepcopy(available_attrs[n]) for n in requested_attrs]
                metrics = [deepcopy(available_metrics[n]) for n in requested_metrics]
                output = {"name": key[0], "version": spec["version"], "attributes": attrs, "metrics": metrics}
                output["lineage"] = deepcopy(parent.get("lineage") or []) + [
                    {"name": parent["name"], "version": parent["version"]}]
            else:
                if set(spec) - {"name", "version", "description", "owner", "attributes", "metrics", "require_native_contract"}:
                    raise ValueError(f"{location}: unsupported contract properties")
                attrs = deepcopy(spec.get("attributes"))
                metrics = deepcopy(spec.get("metrics") or [])
                output = deepcopy(spec)
                output["metrics"] = metrics
                output["lineage"] = []
            _validate_attributes(attrs, location)
            _validate_metrics(metrics, attrs, location)
            if output.get("name") != key[0] or str(output.get("version")) != key[1]:
                raise ValueError(f"{location}: resolved contract identity mismatch")
            resolved[key] = output
            return output
        finally:
            visiting.pop()

    for key in sorted(raw):
        resolve(key)
    return resolved


def resolve_contract(path, name, version):
    registry = load_registry(path)
    key = (name, str(version))
    if key not in registry:
        raise ValueError(f"Unknown CDO contract/version {key}")
    return registry[key]


def main():
    """Validate the entire registry without modifying source files."""
    import argparse
    parser = argparse.ArgumentParser(description="Validate all versioned CDO concepts")
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    definitions = load_registry(args.registry)
    for name, version in sorted(definitions):
        item = definitions[(name, version)]
        print(f"VALID {name} v{version}: {len(item['attributes'])} attributes; "
              f"{len(item['metrics'])} metrics; {len(item['lineage'])} parents")


if __name__ == "__main__":
    main()
