"""Expand references inside model.metrics from a CDO-owned semantic registry.

Custom pre-dbt-parse authoring extension, NOT native dbt metric inheritance.
The same central definition file owns required columns and reusable metrics.
"""

from copy import deepcopy
from pathlib import Path
import re

import yaml


_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _registry(registry_path: Path) -> dict:
    """Return {(metric_name, version): (metric, central_definition)}."""
    path = Path(registry_path)
    files = (sorted(path.rglob("*.yml")) + sorted(path.rglob("*.yaml"))
             if path.is_dir() else [path])
    if not files:
        raise ValueError(f"No central CDO definition YAML files found at {path}")
    specs = {}
    for file in files:
        document = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"Invalid central definition: {file}")
        if not isinstance(document.get("required_columns"), dict):
            raise ValueError(f"Missing required_columns in central definition: {file}")
        for metric in document.get("metrics") or []:
            if not isinstance(metric, dict):
                raise ValueError(f"Invalid CDO metric entry: {file}")
            key = (metric.get("name"), str(metric.get("version")))
            if not all(key) or key in specs:
                raise ValueError(f"Missing or duplicate metric name/version: {file}")
            definition = metric.get("metric")
            if not isinstance(definition, dict):
                raise ValueError(f"Missing metric calculation: {file}")
            if definition.get("type") != "simple" or definition.get("agg") not in {
                "sum", "count", "average", "min", "max", "count_distinct"
            }:
                raise ValueError(f"Unsupported simple metric definition: {file}")
            if not isinstance(definition.get("expr"), str) or not _IDENTIFIER.fullmatch(definition["expr"]):
                raise ValueError(f"Metric expr must name one standardized column: {file}")
            if definition["expr"] not in document["required_columns"]:
                raise ValueError(f"Metric source column must be in required_columns: {file}")
            specs[key] = (metric, document)
    if not specs:
        raise ValueError(f"No metrics declared in central definitions: {path}")
    return specs


def generate_metrics(project_path: Path, registry_path: Path) -> list[str]:
    """Resolve metric-level config.meta.metric_contract references in team YAML.

    The repository stores the short reference beneath each team's metrics list.
    The generated metric is written into that same YAML in an ephemeral checkout.
    Validation runs before any writes; a repeated generation is idempotent.
    """
    models_dir = Path(project_path) / "models"
    if not models_dir.is_dir():
        raise ValueError(f"Cannot find dbt models directory: {models_dir}")
    specs = _registry(Path(registry_path))
    paths = sorted(models_dir.rglob("*.yml")) + sorted(models_dir.rglob("*.yaml"))
    pending = []
    names_seen = set()
    matches_found = 0

    for path in paths:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not content:
            continue
        if not isinstance(content, dict):
            raise ValueError(f"Invalid properties YAML mapping: {path}")
        changed = False
        for model in content.get("models") or []:
            model_name = model.get("name")
            config_meta = ((model.get("config") or {}).get("meta") or {})
            if "metric_bindings" in config_meta:
                raise ValueError(f"{path}: legacy metric_bindings found; move references inside metrics")
            for metric in model.get("metrics") or []:
                metadata = ((metric.get("config") or {}).get("meta") or {})
                binding = metadata.get("metric_contract")
                if not binding:
                    continue
                matches_found += 1
                if not (model.get("semantic_model") or {}).get("enabled"):
                    raise ValueError(f"{path}: {model_name} must enable semantic_model")
                if not isinstance(binding, dict):
                    raise ValueError(f"{path}: invalid metric_contract on {metric.get('name')}")
                key = (binding.get("implements"), str(binding.get("version")))
                if key not in specs:
                    raise ValueError(f"{path}: unknown metric contract/version {key}")
                central_metric, central_model = specs[key]
                implementation = config_meta.get("semantic_contract") or {}
                if (implementation.get("implements") != central_model["name"]
                        or str(implementation.get("version")) != str(central_model["version"])):
                    raise ValueError(
                        f"{path}: {model_name} must implement "
                        f"{central_model['name']} v{central_model['version']} to use {key[0]}"
                    )
                name = metric.get("name")
                if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
                    raise ValueError(f"{path}: invalid metric name: {name}")
                if name in names_seen:
                    raise ValueError(f"Duplicate governed metric name: {name}")
                names_seen.add(name)

                expr = central_metric["metric"]["expr"]
                cols = {column.get("name") for column in model.get("columns") or []}
                if expr not in cols:
                    raise ValueError(f"{path}: {model_name} lacks metric source column {expr}")

                expected = deepcopy(central_metric["metric"])
                expected["name"] = name
                expected["label"] = metric.get("label") or central_metric.get("label") or name
                expected["description"] = central_metric.get("description") or ""
                expected["config"] = {"meta": {
                    "metric_contract": {
                        "implements": key[0], "version": central_metric["version"]
                    }
                }}

                # Teams may customize the label, but cannot override metric logic
                # or add other unknown fields (which could silently change meaning).
                allowed = {"name", "label", "config", "description"}
                for field in metric.keys():
                    if field not in allowed and metric[field] != expected.get(field):
                        raise ValueError(
                            f"{path}: {name} conflicts with the CDO-owned {field} definition"
                        )
                extra_meta = metadata.keys() - {"metric_contract"}
                if extra_meta:
                    raise ValueError(f"{path}: {name} has unsupported custom meta fields {sorted(extra_meta)}")
                if metric.get("description") not in (None, expected["description"]):
                    raise ValueError(f"{path}: {name} overrides the CDO-owned description")
                if metric != expected:
                    metric.clear()
                    metric.update(expected)
                    changed = True

        if changed:
            pending.append((path, yaml.safe_dump(content, sort_keys=False, width=100, allow_unicode=True)))

    if matches_found == 0:
        raise ValueError("No metric-level config.meta.metric_contract references found in dbt model YAML")
    for path, yaml_content in pending:
        path.write_text(yaml_content, encoding="utf-8")
    return [str(path) for path, _ in pending]
