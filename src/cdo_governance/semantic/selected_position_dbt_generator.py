"""Generate the selected CDO Position view and native semantics.

A selected team metric uses a distinct NULL-padded value column, so SUM/COUNT
never accidentally includes another team's rows. Only validated simple metrics
with column expressions are supported in this POC.
"""
from pathlib import Path
import re
import yaml

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CORE = {"position_id", "report_date", "profit_loss"}
TYPES = {"numeric", "integer", "bigint", "text", "date", "boolean"}
METRIC_TYPES = {"numeric", "integer", "bigint"}


def _id(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


def generate_selected(catalog, output_directory):
    implementations = catalog["implementations"]
    selected = catalog["composition_selection"]
    if not implementations or not selected["sources"]:
        raise ValueError("Empty selected CDO composition")
    defs = {x["name"]: x for x in catalog["attribute_definitions"]}
    common = catalog["common_attributes"]
    if not CORE <= set(common):
        raise ValueError("Selected Position composition is missing required core fields")
    if len(set(common)) != len(common):
        raise ValueError("Duplicate selected CDO attributes")
    for name in common:
        _id(name)
        if name not in defs or defs[name]["data_type"] not in TYPES:
            raise ValueError(f"Invalid CDO attribute definition: {name}")
    dims = [{"name": "source_team", "data_type": "text",
             "dimension": {"type": "categorical"}}]
    for name in common:
        item = {"name": name, "data_type": defs[name]["data_type"],
                "description": defs[name].get("description", "")}
        if name == "position_id":
            item["dimension"] = {"type": "categorical"}
        elif name == "report_date":
            item["granularity"] = "day"
            item["dimension"] = {"type": "time"}
        elif name == "instrument_code":
            item["dimension"] = {"type": "categorical"}
            item["entity"] = {"name": "instrument", "type": "foreign"}
        dims.append(item)

    # All non-CDO fields in this selected composition are extensions.
    extensions = {}
    for source in implementations:
        for field in source["columns"]:
            name = _id(field["name"])
            dtype = str(field["data_type"]).lower()
            if dtype not in TYPES:
                raise ValueError(f"Unsupported selected field type: {dtype}")
            if name not in defs:
                if name in extensions and extensions[name] != dtype:
                    raise ValueError(f"Incompatible extension types for {name}")
                extensions[name] = dtype
    for name, dtype in sorted(extensions.items()):
        dims.append({"name": name, "data_type": dtype,
                     "description": "Selected team extension; NULL on other teams."})

    # Publish precisely the enterprise metrics chosen in the approved config.
    metric_names = set()
    metrics = []
    chosen = selected["enterprise_metrics"]
    if "cdo_total_profit_loss" in chosen:
        pnl = next((m for m in catalog["metric_definitions"]
                    if m["name"] == "total_profit_loss"), None)
        if not pnl or (pnl.get("type"), pnl.get("agg"), pnl.get("expr"),
                       pnl.get("fill_nulls_with")) != ("simple", "sum", "profit_loss", 0):
            raise ValueError("CDO Position governed P&L definition is missing or incompatible")
        metrics.append({**{k: v for k, v in pnl.items() if k != "name"},
                        "name": "cdo_total_profit_loss", "label": "CDO Total Profit Loss"})
        metric_names.add("cdo_total_profit_loss")
    if "cdo_position_row_count" in chosen:
        metrics.append({"name": "cdo_position_row_count", "label": "CDO Position Row Count",
                        "description": "Count of selected Position rows, not globally distinct IDs.",
                        "type": "simple", "agg": "count", "expr": "position_id"})
        metric_names.add("cdo_position_row_count")

    projections = []
    for source in implementations:
        team = _id(source["source_team"])
        columns = {c["name"]: c for c in source["columns"]}
        for metric in source["metrics"]:
            name = _id(metric["name"])
            agg = metric["agg"]
            expr = _id(metric["expr"])
            if agg not in {"sum", "count"} or expr not in columns:
                raise ValueError(f"{team}: unsupported source metric {name}")
            dtype = str(columns[expr]["data_type"]).lower()
            if agg == "sum" and dtype not in METRIC_TYPES:
                raise ValueError(f"{team}: metric {name} cannot SUM {dtype}")
            if any(metric.get(x) is not None for x in
                   ("filter", "offset_window", "offset_to_grain", "non_additive_dimension")):
                raise ValueError(f"{team}: unsupported metric properties on {name}")
            alias = _id("cdo_" + name)
            if alias in metric_names:
                raise ValueError(f"Conflicting CDO metric name: {alias}")
            metric_names.add(alias)
            # A physical helper expression is exposed only to compute its selected
            # metric. SQL is NULL-padded on every non-owning source.
            helper = _id("cdo_value_" + team.lower() + "_" + name)
            if helper in defs or helper in extensions or any(x[0] == helper for x in projections):
                raise ValueError(f"Conflicting metric helper column: {helper}")
            projections.append((helper, source["source_model"], expr, dtype))
            dims.append({"name": helper, "data_type": dtype,
                         "description": f"Internal selected {team} metric input."})
            new_metric = {
                "name": alias,
                "label": "CDO " + (metric.get("label") or name),
                "description": f"Selected {team} metric from {source['semantic_model']}.",
                "type": "simple", "agg": agg, "expr": helper
            }
            for property_name in ("fill_nulls_with",):
                if property_name in metric:
                    new_metric[property_name] = metric[property_name]
            metrics.append(new_metric)
    if not metrics:
        raise ValueError("CDO composition cannot publish zero metrics")

    branches = []
    all_names = list(common) + sorted(extensions)
    for source in implementations:
        name = _id(source["source_model"])
        team = _id(source["source_team"])
        cols = {c["name"]: c for c in source["columns"]}
        fields = [f"    '{team}'::text as source_team"]
        for col in all_names:
            dtype = defs[col]["data_type"] if col in defs else extensions[col]
            fields.append(f"    {col}::{dtype} as {col}" if col in cols
                          else f"    null::{dtype} as {col}")
        for helper, owner, expr, dtype in projections:
            fields.append(f"    {expr}::{dtype} as {helper}" if owner == name
                          else f"    null::{dtype} as {helper}")
        branches.append("select\n" + ",\n".join(fields) +
                        f"\nfrom {{{{ ref('{name}') }}}}")
    sql = ("-- AUTO-GENERATED from approved CDO Position composition selection.\n"
           "{{ config(materialized='view') }}\n\n" +
           "\n\nunion all\n\n".join(branches) + "\n")
    model = {"version": 2, "models": [{
        "name": catalog["name"],
        "description": "Selected, governed CDO Position view.",
        "semantic_model": {"enabled": True, "name": catalog["name"]},
        "primary_entity": "cdo_position",
        "agg_time_dimension": "report_date",
        "columns": dims,
        "metrics": metrics,
    }]}
    out = Path(output_directory)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cdo_enterprise_positions.sql").write_text(sql, encoding="utf-8")
    path = out / "cdo_enterprise_positions.yml"
    path.write_text("# AUTO-GENERATED from approved CDO selection; native dbt YAML.\n" +
                    yaml.safe_dump(model, sort_keys=False, allow_unicode=True, width=100),
                    encoding="utf-8")
    return path
