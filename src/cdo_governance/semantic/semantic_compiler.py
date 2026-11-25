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


# Resolve the complete CDO contract graph before expanding team metadata.
# A single file remains supported for legacy, self-contained test fixtures.
from .contract_registry import load_registry


def _load_definitions(path):
    return load_registry(path)


def _normalize_cdo_declaration(model, path):
    """Normalize flat meta.uses, nested meta.cdo, or legacy inheritance metadata."""
    metadata = ((model.get("config") or {}).get("meta") or {})
    flat_keys = {"uses", "version", "include"}
    has_flat = bool(flat_keys & set(metadata))
    has_nested = "cdo" in metadata
    has_legacy = "semantic_inheritance" in metadata
    if sum((has_flat, has_nested, has_legacy)) > 1:
        raise ValueError(f"{path}: use only one inheritance syntax")
    if has_flat:
        declaration = {k: metadata[k] for k in flat_keys if k in metadata}
        location = "meta"
    elif has_nested:
        declaration = metadata["cdo"]
        location = "meta.cdo"
    else:
        return metadata.get("semantic_inheritance")
    if not isinstance(declaration, dict):
        raise ValueError(f"{path}: {location} must be a mapping")
    nested_reference = isinstance(declaration.get("uses"), dict)
    expected_keys = ({"uses", "include"} if nested_reference else flat_keys)
    if set(declaration) != expected_keys:
        if nested_reference:
            raise ValueError(f"{path}: {location} must define uses and include (version belongs inside uses)")
        raise ValueError(f"{path}: {location} must define uses, version, and include")
    if nested_reference:
        reference = declaration["uses"]
        if set(reference) != {"name", "version"}:
            raise ValueError(f"{path}: {location}.uses must contain exactly name and version")
        uses_name, uses_version = reference["name"], reference["version"]
    else:
        uses_name, uses_version = declaration["uses"], declaration["version"]
    if (not isinstance(uses_name, str) or not uses_name.strip()
            or type(uses_version) is not int or uses_version < 1):
        raise ValueError(f"{path}: invalid {location}.uses reference")
    included = declaration["include"]
    if not isinstance(included, dict) or set(included) != {"attributes", "metrics"}:
        raise ValueError(f"{path}: {location}.include must define attributes and metrics")
    attrs, metrics = included["attributes"], included["metrics"]
    if not isinstance(attrs, list) or not attrs or not isinstance(metrics, list):
        raise ValueError(f"{path}: {location} include attributes/metrics must be lists")
    names, context = [], {}
    for attribute in attrs:
        if not isinstance(attribute, dict) or set(attribute) - {"name", "alias", "entity", "dimension", "granularity"}:
            raise ValueError(f"{path}: invalid {location} attribute")
        name = attribute.get("name")
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ValueError(f"{path}: invalid {location} attribute name")
        names.append(name)
        extra = {k: deepcopy(v) for k, v in attribute.items() if k not in {"name", "alias"}}
        alias = attribute.get("alias")
        if alias is not None:
            if not isinstance(alias, str) or not IDENTIFIER.fullmatch(alias):
                raise ValueError(f"{path}: invalid {location} attribute alias for {name}")
            # In dbt v1.12+ semantic names belong to entity.name / dimension.name,
            # while columns[].name remains the actual, CDO-governed database column.
            # Bare columns cannot expose independent semantic aliases via this syntax.
            semantic_keys = [k for k in ("entity", "dimension") if k in extra]
            if len(semantic_keys) != 1:
                raise ValueError(f"{path}: attribute alias {name} requires exactly one entity or dimension")
            semantic_key = semantic_keys[0]
            semantic = extra[semantic_key]
            if not isinstance(semantic, dict):
                raise ValueError(f"{path}: {name} {semantic_key} must be a mapping")
            if "name" in semantic and semantic["name"] != alias:
                raise ValueError(f"{path}: {name} alias conflicts with {semantic_key}.name")
            semantic["name"] = alias
        if extra:
            context[name] = extra
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate include attribute")
    aliases, labels = {}, {}
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) - {"name", "alias", "label"}:
            raise ValueError(f"{path}: invalid {location} metric")
        name, alias = metric.get("name"), metric.get("alias")
        if not isinstance(name, str) or not isinstance(alias, str):
            raise ValueError(f"{path}: each inherited metric requires name and alias")
        if name in aliases:
            raise ValueError(f"{path}: duplicate inherited metric {name}")
        aliases[name] = alias
        if "label" in metric:
            if not isinstance(metric["label"], str):
                raise ValueError(f"{path}: inherited metric label must be text")
            labels[name] = metric["label"]
    return {
        "extends": uses_name,
        "version": uses_version,
        "include": names,
        "context": {"columns": context, "agg_time_dimension": model.get("agg_time_dimension")},
        "metric_aliases": aliases,
        "metric_labels": labels,
    }


def _compile_model(model, definitions, path, bindings=None):
    config = model.get("config") or {}
    metadata = config.get("meta") or {}
    inheritance = _normalize_cdo_declaration(model, path)
    if inheritance is None:
        return False
    if not isinstance(inheritance, dict):
        raise ValueError(f"{path}: semantic_inheritance must be a mapping")
    key = (inheritance.get("extends"), str(inheritance.get("version")))
    if key not in definitions:
        raise ValueError(f"{path}: unknown CDO parent/version {key}")
    parent = definitions[key]
    # Whitelist is mandatory: no implicit inheritance of newly added CDO fields.
    include = inheritance.get("include")
    if not isinstance(include, list) or not include or any(not isinstance(x, str) for x in include):
        raise ValueError(f"{path}: semantic_inheritance.include must be a non-empty list")
    if len(include) != len(set(include)):
        raise ValueError(f"{path}: duplicate include attribute")
    registry_columns = {column["name"]: column for column in parent["attributes"]}
    unknown = set(include) - set(registry_columns)
    if unknown:
        raise ValueError(f"{path}: unknown CDO attributes in include: {sorted(unknown)}")

    # Context is owned by the team, never centrally imposed by a CDO definition.
    context = inheritance.get("context") or {}
    if not isinstance(context, dict) or set(context) - {"columns", "agg_time_dimension"}:
        raise ValueError(f"{path}: invalid semantic_inheritance.context")
    col_context = context.get("columns") or {}
    if not isinstance(col_context, dict) or set(col_context) - set(include):
        raise ValueError(f"{path}: context.columns must reference included attributes only")
    for name, override in col_context.items():
        if not isinstance(override, dict) or set(override) & {"name", "data_type", "description"}:
            raise ValueError(f"{path}: {name} context must not override CDO name/type/description")
    if not (model.get("semantic_model") or {}).get("enabled"):
        raise ValueError(f"{path}: inherited model must enable semantic_model")
    agg_time = context.get("agg_time_dimension")
    if agg_time is not None:
        if agg_time not in include:
            raise ValueError(f"{path}: agg_time_dimension must be included")
        if model.get("agg_time_dimension") not in (None, agg_time):
            raise ValueError(f"{path}: conflicting team agg_time_dimension")
        model["agg_time_dimension"] = agg_time

    inherited_columns = []
    for name in include:
        column = deepcopy(registry_columns[name])
        column.update(deepcopy(col_context.get(name) or {}))
        inherited_columns.append(column)

    local_columns = model.get("columns") or []
    if not isinstance(local_columns, list):
        raise ValueError(f"{path}: columns must be a list")
    inherited_names = set(include)
    additional_names = set()
    for col in local_columns:
        if not isinstance(col, dict) or not col.get("name"):
            raise ValueError(f"{path}: invalid local column")
        if col["name"] in inherited_names:
            raise ValueError(f"{path}: cannot redeclare CDO column {col['name']}")
        if col["name"] in additional_names:
            raise ValueError(f"{path}: duplicate team column {col['name']}")
        additional_names.add(col["name"])
    model["columns"] = inherited_columns + deepcopy(local_columns)

    # Keep metric contracts in the resolved cdo.position definition. Team aliases
    # opt in to metrics, and their referenced attributes must be whitelisted.
    alias_metrics = inheritance.get("metric_aliases") or {}
    metric_labels = inheritance.get("metric_labels") or {}
    if not isinstance(alias_metrics, dict) or not isinstance(metric_labels, dict):
        raise ValueError(f"{path}: metric aliases/labels must be mappings")
    # The reference's CDO namespace comes from 'uses: cdo.position'.
    # Both structured and legacy team declarations resolve to local metric names.
    prefix = parent["name"].split(".")[0] + "."
    alias_metrics = {(k[len(prefix):] if k.startswith(prefix) else k): v for k, v in alias_metrics.items()}
    metric_labels = {(k[len(prefix):] if k.startswith(prefix) else k): v for k, v in metric_labels.items()}
    available_metric_names = {m["name"] for m in parent.get("metrics") or []}
    unexpected = (set(alias_metrics) | set(metric_labels)) - available_metric_names
    if unexpected:
        raise ValueError(f"{path}: unknown CDO metrics {sorted(unexpected)}")
    inherited_metrics = []
    for metric in parent.get("metrics") or []:
        name = alias_metrics.get(metric["name"])
        if not name:
            continue
        if not IDENTIFIER.fullmatch(name):
            raise ValueError(f"{path}: invalid metric alias {name}")
        expression = metric.get("expr")
        if expression not in include:
            raise ValueError(f"{path}: metric {metric['name']} requires included attribute {expression}")
        generated = {k: deepcopy(v) for k, v in metric.items() if k not in {"name", "description"}}
        generated.update({
            "name": name,
            "label": metric_labels.get(metric["name"]) or metric.get("label") or name,
            "description": metric.get("description") or "",
        })
        inherited_metrics.append(generated)
    local_metrics = model.get("metrics") or []
    if not isinstance(local_metrics, list):
        raise ValueError(f"{path}: metrics must be a list")
    names = [m["name"] for m in inherited_metrics] + [m.get("name") for m in local_metrics]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate metric alias/local name")
    model["metrics"] = inherited_metrics + deepcopy(local_metrics)

    # Transport the contract identity and selections in a temporary CI artifact,
    # never inside the deployable dbt semantic YAML.
    expected = {"implements": parent["name"], "version": parent["version"]}
    contract = metadata.get("semantic_contract")
    if contract and any(contract.get(k) != v for k, v in expected.items()):
        raise ValueError(f"{path}: conflicting semantic_contract")
    resolved_contract = {
        **expected,
        "included_attributes": deepcopy(include),
        "included_metrics": list(alias_metrics),
        "lineage": deepcopy(parent.get("lineage") or []),
    }
    if bindings is not None:
        name = model["name"]
        if name in bindings:
            raise ValueError(f"{path}: duplicate CDO implementation {name}")
        bindings[name] = {
            "semantic_contract": resolved_contract,
            "metric_contracts": {
                alias_metrics[m["name"]]: {"implements": m["name"], "version": parent["version"]}
                for m in parent.get("metrics") or [] if m["name"] in alias_metrics
            },
        }
    for authored_key in ("uses", "version", "include", "cdo",
                         "semantic_inheritance", "semantic_contract"):
        metadata.pop(authored_key, None)
    if metadata:
        config["meta"] = metadata
    else:
        config.pop("meta", None)
    model["config"] = config
    return True


def compile_semantics(project_path: Path, registry_path: Path,
                      bindings_output: Path | None = None) -> list[str]:
    """Expand inheritance in models YAML. Validate every file before writing any."""
    project = Path(project_path)
    models = project / "models"
    if not models.is_dir():
        raise ValueError(f"Models directory not found: {models}")
    definitions = _load_definitions(registry_path)
    pending = []
    bindings = {}
    count = 0
    for path in sorted(models.rglob("*.yml")) + sorted(models.rglob("*.yaml")):
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        if content is None:
            continue
        if not isinstance(content, dict):
            raise ValueError(f"{path}: expected YAML mapping")
        changed = False
        for model in content.get("models") or []:
            if _compile_model(model, definitions, path, bindings):
                count += 1
                changed = True
        if changed:
            pending.append((path, yaml.safe_dump(content, sort_keys=False, width=100, allow_unicode=True)))
    if not count:
        raise ValueError("No semantic_inheritance declarations found; refusing empty build")
    if bindings_output is not None:
        bindings_output = Path(bindings_output)
        if bindings_output.resolve().is_relative_to(models.resolve()):
            raise ValueError("Bindings must not be written inside dbt models")
        payload = {"format": "cdo-resolved-bindings/v1", "models": bindings}
        binding_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    for path, text in pending:
        path.write_text(text, encoding="utf-8")
    if bindings_output is not None:
        bindings_output.parent.mkdir(parents=True, exist_ok=True)
        bindings_output.write_text(binding_text, encoding="utf-8")
    return [str(path) for path, _ in pending]


def main():
    """CLI entry point for compiling CDO inheritance before dbt parse."""
    import argparse

    parser = argparse.ArgumentParser(description="Compile CDO semantic inheritance into native dbt YAML")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--bindings-output", type=Path)
    args = parser.parse_args()
    changed = compile_semantics(args.project, args.registry, args.bindings_output)
    print(f"Compiled semantic inheritance in {len(changed)} YAML file(s)")


if __name__ == "__main__":
    main()
