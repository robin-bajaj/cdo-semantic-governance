"""Unit tests for unified CDO business definition and metric-level references."""

import pytest
import yaml

from meta_context_validator.metric_generator import generate_metrics


CENTRAL = {
    "name": "cdo.position",
    "version": 1,
    "required_columns": {
        "position_id": "text", "report_date": "date",
        "profit_loss": "numeric", "instrument_code": "integer",
    },
    "metrics": [{
        "name": "cdo.profit_loss",
        "version": 1,
        "label": "Profit and Loss",
        "description": "Shared P&L aggregation",
        "metric": {"type": "simple", "agg": "sum", "expr": "profit_loss", "fill_nulls_with": 0}
    }]
}


def setup_project(tmp_path):
    registry = tmp_path / "position_v1.yml"
    registry.write_text(yaml.safe_dump(CENTRAL))
    project = tmp_path / "project"
    models = project / "models"
    models.mkdir(parents=True)
    for team, name in [("team_a", "equity_profit_loss"), ("team_c", "fixed_income_profit_loss")]:
        document = {
            "version": 2,
            "models": [{
                "name": f"stg_{team}_positions",
                "config": {"meta": {"semantic_contract": {"implements": "cdo.position", "version": 1}}},
                "semantic_model": {"enabled": True, "name": f"{team}_positions"},
                "columns": [{"name": "profit_loss", "data_type": "numeric"}],
                "metrics": [
                    {"name": name, "label": f"{team} P&L", "config": {"meta": {
                        "metric_contract": {"implements": "cdo.profit_loss", "version": 1}
                    }}},
                    {"name": f"{team}_position_count", "type": "simple", "agg": "count", "expr": "position_id"}
                ]
            }]
        }
        (models / f"{team}.yml").write_text(yaml.safe_dump(document, sort_keys=False))
    return project, registry


def read_metric(project, team):
    file = project / "models" / f"{team}.yml"
    data = yaml.safe_load(file.read_text())
    return data["models"][0]["metrics"][0]


def test_both_teams_share_definition_and_generation_is_idempotent(tmp_path):
    project, registry = setup_project(tmp_path)
    assert len(generate_metrics(project, registry)) == 2
    for team, name in [("team_a", "equity_profit_loss"), ("team_c", "fixed_income_profit_loss")]:
        metric = read_metric(project, team)
        assert metric["name"] == name
        assert metric["type"] == "simple"
        assert metric["agg"] == "sum"
        assert metric["expr"] == "profit_loss"
        assert metric["fill_nulls_with"] == 0
        assert metric["config"]["meta"]["metric_contract"] == {
            "implements": "cdo.profit_loss", "version": 1
        }
        data = yaml.safe_load((project / "models" / f"{team}.yml").read_text())
        assert len(data["models"][0]["metrics"]) == 2
    assert generate_metrics(project, registry) == []


def test_unknown_reference_fails_before_writing_any_files(tmp_path):
    project, registry = setup_project(tmp_path)
    file = project / "models" / "team_c.yml"
    data = yaml.safe_load(file.read_text())
    data["models"][0]["metrics"][0]["config"]["meta"]["metric_contract"]["implements"] = "cdo.unknown"
    file.write_text(yaml.safe_dump(data))
    before = (project / "models" / "team_a.yml").read_text()
    with pytest.raises(ValueError, match="unknown metric contract"):
        generate_metrics(project, registry)
    assert (project / "models" / "team_a.yml").read_text() == before


def test_missing_profit_column_fails(tmp_path):
    project, registry = setup_project(tmp_path)
    file = project / "models" / "team_a.yml"
    data = yaml.safe_load(file.read_text())
    data["models"][0]["columns"] = []
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="lacks metric source column profit_loss"):
        generate_metrics(project, registry)


def test_unapproved_team_formula_fails(tmp_path):
    project, registry = setup_project(tmp_path)
    file = project / "models" / "team_a.yml"
    data = yaml.safe_load(file.read_text())
    data["models"][0]["metrics"][0]["agg"] = "average"
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="conflicts with the CDO-owned agg"):
        generate_metrics(project, registry)


def test_new_registry_version_requires_explicit_adoption(tmp_path):
    project, registry = setup_project(tmp_path)
    central = yaml.safe_load(registry.read_text())
    central["metrics"][0]["version"] = 2
    registry.write_text(yaml.safe_dump(central))
    with pytest.raises(ValueError, match="unknown metric contract"):
        generate_metrics(project, registry)


def test_model_must_implement_parent_cdo_contract(tmp_path):
    project, registry = setup_project(tmp_path)
    file = project / "models" / "team_a.yml"
    data = yaml.safe_load(file.read_text())
    data["models"][0]["config"]["meta"]["semantic_contract"]["implements"] = "something.else"
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="must implement cdo.position"):
        generate_metrics(project, registry)


def test_legacy_metric_bindings_rejected(tmp_path):
    project, registry = setup_project(tmp_path)
    file = project / "models" / "team_a.yml"
    data = yaml.safe_load(file.read_text())
    data["models"][0]["config"]["meta"]["metric_bindings"] = [{"contract": "cdo.profit_loss"}]
    file.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="legacy metric_bindings"):
        generate_metrics(project, registry)
