"""Independent dbt projects each validate just their own contract implementations."""

from copy import deepcopy

from meta_context_validator.contract_rules import validate_cdo_contract


CONTRACT = {
    "name": "cdo.position",
    "version": 1,
    "semantic_columns": [
        {"name": "position_id", "data_type": "text"},
        {"name": "report_date", "data_type": "date"},
        {"name": "profit_loss", "data_type": "numeric"},
        {"name": "instrument_code", "data_type": "integer"},
    ],
}


def manifest_for(model_name="equity_positions"):
    return {
        "nodes": {
            f"model.equity.{model_name}": {
                "resource_type": "model",
                "name": model_name,
                "config": {
                    "meta": {
                        "semantic_contract": {
                            "implements": "cdo.position",
                            "version": 1,
                        }
                    }
                },
                "columns": {
                    "position_id": {"data_type": "text"},
                    "report_date": {"data_type": "date"},
                    "profit_loss": {"data_type": "numeric"},
                    "instrument_code": {"data_type": "integer"},
                    "team_specific_optional": {"data_type": "text"},
                },
            }
        }
    }


def test_team_can_use_any_model_name():
    assert validate_cdo_contract(manifest_for("equity_positions"), CONTRACT) == []
    assert validate_cdo_contract(manifest_for("fi_book_positions"), CONTRACT) == []


def test_missing_column_fails_on_single_project():
    manifest = manifest_for()
    del manifest["nodes"]["model.equity.equity_positions"]["columns"]["profit_loss"]
    errors = validate_cdo_contract(manifest, CONTRACT)
    assert any("Missing mandatory column profit_loss" in error for error in errors)


def test_version_mismatch_fails_on_single_project():
    manifest = manifest_for()
    manifest["nodes"]["model.equity.equity_positions"]["config"]["meta"]["semantic_contract"]["version"] = 2
    errors = validate_cdo_contract(manifest, CONTRACT)
    assert any("version mismatch" in error for error in errors)


def test_no_implementation_fails_closed():
    assert "No models" in validate_cdo_contract({"nodes": {}}, CONTRACT)[0]
    manifest = manifest_for()
    del manifest["nodes"]["model.equity.equity_positions"]["config"]["meta"]["semantic_contract"]
    assert "No models" in validate_cdo_contract(manifest, CONTRACT)[0]


def test_legacy_required_models_remains_supported():
    contract = deepcopy(CONTRACT)
    contract["required_models"] = ["equity_positions"]
    assert validate_cdo_contract(manifest_for(), contract) == []
    contract["required_models"] = ["absent_position"]
    assert "Model not found" in validate_cdo_contract(manifest_for(), contract)[0]


def test_unrelated_models_are_ignored():
    manifest = manifest_for()
    manifest["nodes"]["model.equity.unrelated"] = {
        "resource_type": "model",
        "name": "unrelated",
        "columns": {},
        "config": {},
    }
    assert validate_cdo_contract(manifest, CONTRACT) == []


def test_native_contract_required_for_opted_in_models():
    contract = deepcopy(CONTRACT)
    contract["require_native_contract"] = True
    manifest = manifest_for()
    errors = validate_cdo_contract(manifest, contract)
    assert any("Native dbt contract is not enforced" in error for error in errors)

    node = manifest["nodes"]["model.equity.equity_positions"]
    node["config"]["contract"] = {"enforced": True}
    assert validate_cdo_contract(manifest, contract) == []


def test_unrelated_model_not_forced_to_enforce_cdo_contract():
    contract = deepcopy(CONTRACT)
    contract["require_native_contract"] = True
    manifest = manifest_for()
    manifest["nodes"]["model.equity.equity_positions"]["config"]["contract"] = {
        "enforced": True,
    }
    manifest["nodes"]["model.equity.independent"] = {
        "resource_type": "model",
        "name": "independent",
        "columns": {},
        "config": {"contract": {"enforced": False}},
    }
    assert validate_cdo_contract(manifest, contract) == []
