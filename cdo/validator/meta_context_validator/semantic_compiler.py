"""Compile CDO semantic-model inheritance into native dbt model properties.

This is a custom pre-parse build step, not a dbt-native `extends` feature.
It operates on a checked-out project. It does not push to remote Git.
"""
from copy import deepcopy
from pathlib import Path
import re

import yaml


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_yaml(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return data


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


def _load_definitions(path):
    definitions = {}
    for file in _definition_files(path):
        spec = _read_yaml(file)
        key = (spec.get("name"), str(spec.get("version")))
        if not key[0] or key in definitions:
            raise ValueError(f"{file}: missing or duplicated CDO name/version")
        columns = spec.get("semantic_columns")
        if "required_columns" in spec:
            raise ValueError(f"{file}: use semantic_columns only, not required_columns")
        if not isinstance(columns, list) or not columns:
            raise ValueError(f"{file}: expected non-empty semantic_columns")
        names = []
        for col in columns:
            if not isinstance(col, dict):
                raise ValueError(f"{file}: invalid inherited column")
            name, dtype = col.get("name"), col.get("data_type")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"{file}: invalid inherited column name")
            if not isinstance(dtype, str) or not dtype.strip():
                raise ValueError(f"{file}: column {name} requires data_type")
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError(f"{file}: duplicate inherited column names")
        required = set(names)
        metrics = spec.get("metrics") or []
        if not isinstance(metrics, list):
            raise ValueError(f"{file}: metrics must be a list")
        for m in metrics:
            if not isinstance(m, dict) or not m.get("name") or not m.get("version"):
                raise ValueError(f"{file}: invalid metric declaration")
            formula = m.get("metric")
            if not isinstance(formula, dict) or formula.get("type") != "simple":
                raise ValueError(f"{file}: only simple metrics are currently supported")
            if formula.get("agg") not in {"sum", "count", "average", "min", "max", "count_distinct"}:
                raise ValueError(f"{file}: invalid aggregation on {m['name']}")
            if formula.get("expr") not in required:
                raise ValueError(f"{file}: metric {m['name']} references a non-standard column")
        definitions[key] = spec
    return definitions


def _compile_model(model, definitions, path):
    config = model.get("config") or {}
    metadata = config.get("meta") or {}
    inheritance = metadata.get("semantic_inheritance")
    if inheritance is None:
        return False
    if not isinstance(inheritance, dict):
        raise ValueError(f"{path}: semantic_inheritance must be a mapping")
    key = (inheritance.get("extends"), str(inheritance.get("version")))
    if key not in definitions:
        raise ValueError(f"{path}: unknown CDO parent/version {key}")
    parent = definitions[key]
    alias_entities = inheritance.get("entity_aliases") or {}
    alias_metrics = inheritance.get("metric_aliases") or {}
    metric_labels = inheritance.get("metric_labels") or {}
    if not isinstance(alias_entities, dict) or not isinstance(alias_metrics, dict) or not isinstance(metric_labels, dict):
        raise ValueError(f"{path}: aliases must be mappings")
    if not (model.get("semantic_model") or {}).get("enabled"):
        raise ValueError(f"{path}: inherited model must enable semantic_model")
    if model.get("agg_time_dimension") not in (None, parent.get("agg_time_dimension")):
        raise ValueError(f"{path}: cannot override CDO aggregation time dimension")
    model["agg_time_dimension"] = parent["agg_time_dimension"]

    inherited_columns = deepcopy(parent["semantic_columns"])
    for col in inherited_columns:
        entity = col.get("entity")
        if entity and entity.get("name") in alias_entities:
            entity["name"] = alias_entities[entity["name"]]
    unexpected = set(alias_entities) - {
        col["entity"]["name"] for col in parent["semantic_columns"] if col.get("entity")
    }
    if unexpected:
        raise ValueError(f"{path}: unknown parent entities {sorted(unexpected)}")
    local_columns = model.get("columns") or []
    if not isinstance(local_columns, list):
        raise ValueError(f"{path}: columns must be a list")
    inherited_names = {col["name"] for col in inherited_columns}
    additional_names = set()
    for col in local_columns:
        if not isinstance(col, dict) or not col.get("name"):
            raise ValueError(f"{path}: invalid local column")
        if col["name"] in inherited_names:
            raise ValueError(f"{path}: cannot redeclare CDO column {col['name']}")
        if col["name"] in additional_names:
            raise ValueError(f"{path}: duplicate team column {col['name']}")
        additional_names.add(col["name"])
    # Additional local columns are appended, never overwrite inherited columns.
    model["columns"] = inherited_columns + deepcopy(local_columns)

    available_metric_names = {m["name"] for m in parent.get("metrics") or []}
    unexpected = (set(alias_metrics) | set(metric_labels)) - available_metric_names
    if unexpected:
        raise ValueError(f"{path}: unknown parent metrics {sorted(unexpected)}")
    inherited_metrics = []
    for metric in parent.get("metrics") or []:
        name = alias_metrics.get(metric["name"])
        if not name:
            raise ValueError(f"{path}: metric_aliases must name {metric['name']}")
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"{path}: invalid metric alias {name}")
        generated = deepcopy(metric["metric"])
        generated.update({
            "name": name,
            "label": metric_labels.get(metric["name"]) or metric.get("label") or name,
            "description": metric.get("description") or "",
            "config": {"meta": {"metric_contract": {
                "implements": metric["name"],
                "version": metric["version"],
            }}},
        })
        inherited_metrics.append(generated)
    local_metrics = model.get("metrics") or []
    if not isinstance(local_metrics, list):
        raise ValueError(f"{path}: metrics must be a list")
    names = [m["name"] for m in inherited_metrics] + [m.get("name") for m in local_metrics]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate metric alias/local name")
    model["metrics"] = inherited_metrics + deepcopy(local_metrics)

    # Keep original inheritance declaration for traceability, but inject the
    # existing semantic_contract marker for dbt manifest-based validation.
    contract = metadata.get("semantic_contract")
    expected = {"implements": parent["name"], "version": parent["version"]}
    if contract and contract != expected:
        raise ValueError(f"{path}: conflicting semantic_contract")
    metadata["semantic_contract"] = expected
    config["meta"] = metadata
    model["config"] = config
    return True


def compile_semantics(project_path: Path, registry_path: Path) -> list[str]:
    """Expand inheritance in models YAML. Validate every file before writing any."""
    project = Path(project_path)
    models = project / "models"
    if not models.is_dir():
        raise ValueError(f"Models directory not found: {models}")
    definitions = _load_definitions(registry_path)
    pending = []
    count = 0
    for path in sorted(models.rglob("*.yml")) + sorted(models.rglob("*.yaml")):
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        if content is None:
            continue
        if not isinstance(content, dict):
            raise ValueError(f"{path}: expected YAML mapping")
        changed = False
        for model in content.get("models") or []:
            if _compile_model(model, definitions, path):
                count += 1
                changed = True
        if changed:
            pending.append((path, yaml.safe_dump(content, sort_keys=False, width=100, allow_unicode=True)))
    if not count:
        raise ValueError("No semantic_inheritance declarations found; refusing empty build")
    for path, text in pending:
        path.write_text(text, encoding="utf-8")
    return [str(path) for path, _ in pending]
