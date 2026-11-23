"""Functional tests of CDO semantic inheritance."""
from copy import deepcopy
import pytest
import yaml
from meta_context_validator.semantic.inheritance import compile_semantics

CDO = {
    "name": "cdo.position", "version": 1, "owner": "CDO",
    "agg_time_dimension": "report_date",
    "semantic_columns": [
        {"name": "position_id", "data_type": "text", "entity": {"name": "position", "type": "primary"}},
        {"name": "report_date", "data_type": "date", "granularity": "day", "dimension": {"type": "time"}},
        {"name": "profit_loss", "data_type": "numeric"},
        {"name": "instrument_code", "data_type": "integer", "entity": {"name": "instrument", "type": "foreign"}},
    ],
    "metrics": [{"name": "cdo.profit_loss", "version": 1, "label": "Profit and Loss",
                 "metric": {"type": "simple", "agg": "sum", "expr": "profit_loss", "fill_nulls_with": 0}}],
}

def project(tmp_path):
    root = tmp_path / "dbt"
    (root / "models").mkdir(parents=True)
    central = tmp_path / "position_v1.yml"
    central.write_text(yaml.safe_dump(CDO))
    for team in ("team_a", "team_c"):
        model = {"version": 2, "models": [{
            "name": f"stg_{team}_positions", "config": {"meta": {
                "semantic_inheritance": {
                    "extends": "cdo.position", "version": 1,
                    "entity_aliases": {"position": f"{team}_position"},
                    "metric_aliases": {"cdo.profit_loss": f"{team}_profit_loss"},
                    "metric_labels": {"cdo.profit_loss": f"{team} Profit and Loss"}
                }
            }},
            "semantic_model": {"enabled": True, "name": f"{team}_positions"},
            "columns": [{"name": "mtm" if team == "team_a" else "settled_cash", "data_type": "numeric"}],
            "metrics": [{"name": f"{team}_count", "type": "simple", "agg": "count", "expr": "position_id"}]
        }]}
        (root / "models" / f"{team}.yml").write_text(yaml.safe_dump(model))
    return root, central

def test_inherits_all_columns_entities_dimensions_and_formula(tmp_path):
    root, central = project(tmp_path)
    assert len(compile_semantics(root, central)) == 2
    for team in ("team_a", "team_c"):
        model = yaml.safe_load((root / "models" / f"{team}.yml").read_text())["models"][0]
        cols = {x["name"]: x for x in model["columns"]}
        assert cols["position_id"]["entity"]["name"] == f"{team}_position"
        assert cols["report_date"]["dimension"]["type"] == "time"
        assert cols["instrument_code"]["entity"]["type"] == "foreign"
        assert model["agg_time_dimension"] == "report_date"
        assert model["metrics"][0]["label"] == f"{team} Profit and Loss"
        assert model["metrics"][0]["agg"] == "sum"
        assert model["metrics"][0]["expr"] == "profit_loss"
        assert model["metrics"][0]["name"] == f"{team}_profit_loss"
        assert model["config"]["meta"]["semantic_contract"]["implements"] == "cdo.position"
        assert len(model["columns"]) == 5
        assert len(model["metrics"]) == 2

def test_invalid_team_override_rejected_without_partial_write(tmp_path):
    root, central = project(tmp_path)
    a = root / "models" / "team_a.yml"
    b = root / "models" / "team_c.yml"
    model = yaml.safe_load(b.read_text())
    model["models"][0]["columns"].append({"name": "profit_loss", "data_type": "text"})
    b.write_text(yaml.safe_dump(model))
    before = a.read_text()
    with pytest.raises(ValueError, match="cannot redeclare CDO column"):
        compile_semantics(root, central)
    assert a.read_text() == before

def test_unknown_version_fails(tmp_path):
    root, central = project(tmp_path)
    path = root / "models" / "team_c.yml"
    data = yaml.safe_load(path.read_text())
    data["models"][0]["config"]["meta"]["semantic_inheritance"]["version"] = 2
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="unknown CDO parent/version"):
        compile_semantics(root, central)

def test_missing_semantic_column_type_rejected(tmp_path):
    root, central = project(tmp_path)
    definition = deepcopy(CDO)
    del definition["semantic_columns"][2]["data_type"]
    central.write_text(yaml.safe_dump(definition))
    with pytest.raises(ValueError, match="requires data_type"):
        compile_semantics(root, central)


def test_duplicate_semantic_column_rejected(tmp_path):
    root, central = project(tmp_path)
    definition = deepcopy(CDO)
    definition["semantic_columns"].append(deepcopy(definition["semantic_columns"][0]))
    central.write_text(yaml.safe_dump(definition))
    with pytest.raises(ValueError, match="duplicate inherited column names"):
        compile_semantics(root, central)


def test_legacy_duplicate_column_mapping_rejected(tmp_path):
    root, central = project(tmp_path)
    definition = deepcopy(CDO)
    definition["required_columns"] = {"profit_loss": "numeric"}
    central.write_text(yaml.safe_dump(definition))
    with pytest.raises(ValueError, match="use semantic_columns only"):
        compile_semantics(root, central)
