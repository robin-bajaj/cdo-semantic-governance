"""Regression tests for lossless, fail-closed CDO catalog composition."""
from copy import deepcopy
import json
import pytest
import yaml

from cdo_governance.semantic.inheritance import compile_semantics
from cdo_governance.semantic.composition import compose_cdo
from test_semantic_compiler import project


def setup_compiled(tmp_path):
    root, contract_file = project(tmp_path)
    for team in ("team_a", "team_c"):
        path = root / "models" / f"{team}.yml"
        content = yaml.safe_load(path.read_text())
        content["models"][0]["config"]["contract"] = {"enforced": True}
        path.write_text(yaml.safe_dump(content))
    compile_semantics(root, contract_file)
    nodes = {}
    for team in ("team_a", "team_c"):
        model = yaml.safe_load((root / "models" / f"{team}.yml").read_text())["models"][0]
        name = model["name"]
        nodes[f"model.poc.{name}"] = {
            "resource_type": "model", "name": name,
            "unique_id": f"model.poc.{name}",
            "config": deepcopy(model["config"]),
            "columns": {c["name"]: deepcopy(c) for c in model["columns"]},
        }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": nodes}))
    return root, contract_file, manifest


def test_preserves_common_and_all_team_extensions(tmp_path):
    root, contract, manifest = setup_compiled(tmp_path)
    output = tmp_path / "generated" / "cdo" / "position" / "v1" / "cdo_enterprise_positions.yml"
    compose_cdo(root, contract, manifest, output,
                ["team_a_positions", "team_c_positions"])
    result = yaml.safe_load(output.read_text())
    assert result["catalog_format"] == "cdo-federated-semantic-catalog/v1"
    assert result["common_attributes"] == ["position_id", "report_date", "profit_loss", "instrument_code"]
    assert len(result["implementations"]) == 2
    models = {i["semantic_model"]: i for i in result["implementations"]}
    a = models["team_a_positions"]
    c = models["team_c_positions"]
    assert a["included_attributes"] == ["position_id", "report_date", "profit_loss", "instrument_code"]
    assert next(c for c in a["columns"] if c["name"] == "position_id")["entity"]["name"] == "team_a_position"
    assert c["included_attributes"] == ["position_id", "report_date", "profit_loss", "instrument_code"]
    assert next(c for c in c["columns"] if c["name"] == "position_id")["entity"]["name"] == "team_c_position"
    assert "mtm" in {col["name"] for col in a["columns"]}
    assert "settled_cash" in {col["name"] for col in c["columns"]}
    assert {m["name"] for m in a["metrics"]} == {"team_a_profit_loss", "team_a_count"}
    assert {m["name"] for m in c["metrics"]} == {"team_c_profit_loss", "team_c_count"}
    assert "enterprise_metrics" not in result
    before = output.read_bytes()
    compose_cdo(root, contract, manifest, output,
                ["team_a_positions", "team_c_positions"])
    assert output.read_bytes() == before


def test_rejects_missing_participating_team(tmp_path):
    root, contract, manifest = setup_compiled(tmp_path)
    data = json.loads(manifest.read_text())
    data["nodes"].pop("model.poc.stg_team_c_positions")
    manifest.write_text(json.dumps(data))
    output = tmp_path / "generated" / "cdo.yml"
    with pytest.raises(ValueError, match="Missing expected semantic models"):
        compose_cdo(root, contract, manifest, output,
                    expected_teams=["team_a_positions", "team_c_positions"])
    assert not output.exists()


def test_rejects_attempt_to_write_to_dbt_models(tmp_path):
    root, contract, manifest = setup_compiled(tmp_path)
    with pytest.raises(ValueError, match="must not be inside"):
        compose_cdo(root, contract, manifest, root / "models" / "generated.yml")


def test_rejects_incorrect_compiled_inherited_metric(tmp_path):
    root, contract, manifest = setup_compiled(tmp_path)
    path = root / "models" / "team_a.yml"
    content = yaml.safe_load(path.read_text())
    content["models"][0]["metrics"][0]["agg"] = "max"
    path.write_text(yaml.safe_dump(content))
    with pytest.raises(ValueError, match="overrides agg"):
        compose_cdo(root, contract, manifest, tmp_path / "catalog.yml")


def test_optional_governed_attribute_may_be_omitted_by_team(tmp_path):
    fresh_root, fresh_contract = project(tmp_path / "other")
    for team in ("team_a", "team_c"):
        path = fresh_root / "models" / f"{team}.yml"
        obj = yaml.safe_load(path.read_text())
        obj["models"][0]["config"]["contract"] = {"enforced": True}
        if team == "team_c":
            cfg = obj["models"][0]["config"]["meta"]["semantic_inheritance"]
            cfg["include"].remove("instrument_code")
            cfg["context"]["columns"].pop("instrument_code")
        path.write_text(yaml.safe_dump(obj))
    compile_semantics(fresh_root, fresh_contract)
    nodes = {}
    for team in ("team_a", "team_c"):
        m = yaml.safe_load((fresh_root / "models" / f"{team}.yml").read_text())["models"][0]
        nodes["model.poc." + m["name"]] = {
            "resource_type": "model", "name": m["name"], "unique_id": "model.poc." + m["name"],
            "config": deepcopy(m["config"]),
            "columns": {c["name"]: deepcopy(c) for c in m["columns"]},
        }
    manifest = tmp_path / "optional-manifest.json"
    manifest.write_text(json.dumps({"nodes": nodes}))
    output = tmp_path / "optional-catalog.yml"
    compose_cdo(fresh_root, fresh_contract, manifest, output)
    data = yaml.safe_load(output.read_text())
    implementations = {i["semantic_model"]: i for i in data["implementations"]}
    assert "instrument_code" in data["common_attributes"]
    assert "instrument_code" not in implementations["team_c_positions"]["included_attributes"]
