"""CDO-owned, reviewable selection of validated semantic implementations.

This file does not define the CDO business contract. It chooses which
implementations and their native fields/metrics the enterprise publication uses.
"""
from copy import deepcopy
from pathlib import Path
import re
import yaml

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CORE = {"position_id", "report_date", "profit_loss"}
ENTERPRISE_METRICS = {"cdo_total_profit_loss", "cdo_position_row_count"}
UNSUPPORTED_PROPERTIES = ("filter", "offset_window", "offset_to_grain", "non_additive_dimension")


def _ident(value, label):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _names(value, label, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{label}: expected {'a' if allow_empty else 'nonempty'} list")
    for item in value:
        _ident(item, label)
    if len(value) != len(set(value)):
        raise ValueError(f"{label}: duplicate entries")
    return value


def _eligible_metric(metric, source_columns, selected_attributes=None):
    if metric.get("type") != "simple" or metric.get("agg") not in {"sum", "count"}:
        return False
    expr = metric.get("expr")
    if not isinstance(expr, str) or not IDENT.fullmatch(expr):
        return False
    available = source_columns if selected_attributes is None else selected_attributes
    if expr not in available or any(metric.get(p) is not None for p in UNSUPPORTED_PROPERTIES):
        return False
    if metric["agg"] == "sum":
        column = source_columns[expr]
        return column.get("data_type", "").lower() in {"numeric", "integer", "bigint"}
    return True


def _semantic_attribute(column):
    """Describe a validated source column's semantic role without renaming it.

    CDO composition still selects canonical physical column identifiers.
    Entity/dimension names are descriptive discovery metadata, not CDO aliases.
    """
    field = {"name": column["name"], "data_type": column.get("data_type")}
    entity = column.get("entity")
    dimension = column.get("dimension")
    if entity is not None:
        if not isinstance(entity, dict):
            raise ValueError(f"{column['name']}: invalid semantic entity")
        field["semantic_entity"] = entity.get("name") or column["name"]
        field["entity_type"] = entity.get("type")
    if dimension is not None:
        if not isinstance(dimension, dict):
            raise ValueError(f"{column['name']}: invalid semantic dimension")
        field["semantic_dimension"] = dimension.get("name") or column["name"]
        field["dimension_type"] = dimension.get("type")
        if column.get("granularity") is not None:
            field["granularity"] = column["granularity"]
    return field


def available_implementations(catalog):
    """Discovery lists candidates and supported metrics WITHOUT applying a selection."""
    available = []
    for impl in catalog["implementations"]:
        cols = {col["name"]: col for col in impl["columns"]}
        available.append({
            "semantic_model": impl["semantic_model"],
            "source_model": impl["source_model"],
            "owner": impl.get("owner"),
            "attributes": [col["name"] for col in impl["columns"]],
            "attribute_semantics": [_semantic_attribute(col) for col in impl["columns"]],
            "metrics": [
                m["name"] for m in impl["metrics"]
                if _eligible_metric(m, cols)
            ],
        })
    return {"contract": deepcopy(catalog["contract"]), "available_implementations": available,
            "enterprise_metrics": sorted(ENTERPRISE_METRICS)}


def select_composition(catalog, selection_path):
    """Validate an explicit CDO selection, then filter a fully validated catalog.

    Full contract/metric validation occurs in the composer *before* this stage.
    All source names and fields must come from the validated catalog.
    """
    selection = yaml.safe_load(Path(selection_path).read_text(encoding="utf-8"))
    if not isinstance(selection, dict) or set(selection) != {"name", "contract", "sources", "enterprise_metrics"}:
        raise ValueError("CDO selection must contain name, contract, sources and enterprise_metrics")
    if selection["name"] != catalog["name"] or selection["contract"] != catalog["contract"]:
        raise ValueError("CDO selection name or contract version does not match validated catalog")
    sources = selection["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("CDO selection must choose at least one source")
    enterprise = _names(selection["enterprise_metrics"], "enterprise_metrics", allow_empty=True)
    unknown = set(enterprise) - ENTERPRISE_METRICS
    if unknown:
        raise ValueError(f"Unsupported CDO enterprise metrics: {sorted(unknown)}")
    choices = {i["semantic_model"]: i for i in catalog["implementations"]}
    selected = []
    used = set()
    team_labels = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"semantic_model", "source_team", "include"}:
            raise ValueError("Each CDO source requires semantic_model, source_team and include")
        name = _ident(source["semantic_model"], "semantic_model")
        team = _ident(source["source_team"], "source_team")
        if name in used or team in team_labels:
            raise ValueError(f"Duplicate CDO selection model or source_team: {name}/{team}")
        used.add(name)
        team_labels.add(team)
        if name not in choices:
            raise ValueError(f"Unvalidated CDO semantic model selected: {name}")
        if not isinstance(source["include"], dict) or set(source["include"]) != {"attributes", "metrics"}:
            raise ValueError(f"{name}: include must contain attributes and metrics")
        requested_attrs = _names(source["include"]["attributes"], f"{name}.attributes")
        requested_metrics = _names(source["include"]["metrics"], f"{name}.metrics", allow_empty=True)
        candidate = choices[name]
        columns = {c["name"]: c for c in candidate["columns"]}
        metrics = {m["name"]: m for m in candidate["metrics"]}
        allowed = set(candidate["included_attributes"]) | (set(columns) -
                   {c["name"] for c in catalog["attribute_definitions"]})
        invalid = set(requested_attrs) - allowed
        if invalid:
            raise ValueError(f"{name}: attributes not available from validated implementation: {sorted(invalid)}")
        missing = CORE - set(requested_attrs)
        if missing:
            raise ValueError(f"{name}: missing required core Position attributes: {sorted(missing)}")
        unknown_metrics = set(requested_metrics) - set(metrics)
        if unknown_metrics:
            raise ValueError(f"{name}: metrics not found in validated implementation: {sorted(unknown_metrics)}")
        for metric_name in requested_metrics:
            if not _eligible_metric(metrics[metric_name], columns, set(requested_attrs)):
                raise ValueError(f"{name}: metric {metric_name} is unsupported or requires an excluded attribute")
        projected = deepcopy(candidate)
        projected["source_team"] = team
        projected["included_attributes"] = [
            c for c in candidate["included_attributes"] if c in requested_attrs
        ]
        projected["columns"] = [deepcopy(columns[n]) for n in requested_attrs]
        projected["metrics"] = [deepcopy(metrics[n]) for n in requested_metrics]
        selected.append(projected)
    if not enterprise and not any(i["metrics"] for i in selected):
        raise ValueError("CDO composition must publish at least one metric")
    output = deepcopy(catalog)
    output["implementations"] = selected
    allowed_common = {c["name"] for c in catalog["attribute_definitions"]}
    output["common_attributes"] = [
        n for n in catalog["common_attributes"]
        if n in allowed_common and any(n in src["included_attributes"] for src in selected)
    ]
    output["enterprise_metrics"] = enterprise
    output["composition_selection"] = {
        "sources": [
            {"semantic_model": i["semantic_model"], "source_team": i["source_team"],
             "attributes": [c["name"] for c in i["columns"]],
             "metrics": [m["name"] for m in i["metrics"]]}
            for i in selected
        ],
        "enterprise_metrics": list(enterprise),
    }
    return output


def main():
    import argparse
    parser = argparse.ArgumentParser(description="List eligible CDO semantic implementations")
    parser.add_argument("--catalog", required=True, type=Path,
                        help="Fully validated composition catalog, before CDO selection")
    parser.add_argument("--list-implementations", action="store_true", required=True)
    args = parser.parse_args()
    catalog = yaml.safe_load(args.catalog.read_text(encoding="utf-8"))
    print(yaml.safe_dump(available_implementations(catalog), sort_keys=False))


if __name__ == "__main__":
    main()
