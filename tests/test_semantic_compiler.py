"""Functional tests of CDO semantic inheritance."""
from copy import deepcopy
import pytest
import yaml
from cdo_governance.semantic.semantic_compiler import compile_semantics

CDO = {
    "name": "cdo.position", "version": 1, "owner": "CDO",
    "attributes": [
        {"name": "position_id", "data_type": "text", "description": "Position ID"},
        {"name": "report_date", "data_type": "date", "description": "Reporting date"},
        {"name": "profit_loss", "data_type": "numeric", "description": "P&L"},
        {"name": "instrument_code", "data_type": "integer", "description": "Instrument"},
    ],
    "metrics": [{"name": "total_profit_loss", "description": "Profit and Loss",
                 "type": "simple", "agg": "sum", "expr": "profit_loss", "fill_nulls_with": 0}],
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
                    "include": ["position_id", "report_date", "profit_loss", "instrument_code"],
                    "context": {
                        "agg_time_dimension": "report_date",
                        "columns": {
                            "position_id": {"entity": {"name": f"{team}_position", "type": "primary"}},
                            "report_date": {"granularity": "day", "dimension": {"type": "time"}},
                            "instrument_code": {"entity": {"name": "instrument", "type": "foreign"}},
                        },
                    },
                    "metric_aliases": {"total_profit_loss": f"{team}_profit_loss"},
                    "metric_labels": {"total_profit_loss": f"{team} Profit and Loss"}
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
    del definition["attributes"][2]["data_type"]
    central.write_text(yaml.safe_dump(definition))
    with pytest.raises(ValueError, match="requires data_type"):
        compile_semantics(root, central)


def test_duplicate_semantic_column_rejected(tmp_path):
    root, central = project(tmp_path)
    definition = deepcopy(CDO)
    definition["attributes"].append(deepcopy(definition["attributes"][0]))
    central.write_text(yaml.safe_dump(definition))
    with pytest.raises(ValueError, match="duplicate CDO attribute names"):
        compile_semantics(root, central)


def test_legacy_duplicate_column_mapping_rejected(tmp_path):
    root, central = project(tmp_path)
    definition = deepcopy(CDO)
    definition["required_columns"] = {"profit_loss": "numeric"}
    central.write_text(yaml.safe_dump(definition))
    with pytest.raises(ValueError, match="use attributes only"):
        compile_semantics(root, central)


def test_include_selects_only_whitelisted_attributes(tmp_path):
    root, registry = project(tmp_path)
    # Team C opts out of the optional CDO instrument attribute.
    path = root / "models" / "team_c.yml"
    obj = yaml.safe_load(path.read_text())
    inheritance = obj["models"][0]["config"]["meta"]["semantic_inheritance"]
    inheritance["include"].remove("instrument_code")
    inheritance["context"]["columns"].pop("instrument_code")
    path.write_text(yaml.safe_dump(obj))
    compile_semantics(root, registry)
    model = yaml.safe_load(path.read_text())["models"][0]
    assert "instrument_code" not in {c["name"] for c in model["columns"]}
    assert model["config"]["meta"]["semantic_contract"]["included_attributes"] == inheritance["include"]


def test_missing_include_fails_closed(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    obj = yaml.safe_load(path.read_text())
    obj["models"][0]["config"]["meta"]["semantic_inheritance"].pop("include")
    path.write_text(yaml.safe_dump(obj))
    with pytest.raises(ValueError, match="include must be a non-empty"):
        compile_semantics(root, registry)


def test_include_invalid_attribute_and_context_type_override(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    obj = yaml.safe_load(path.read_text())
    inheritance = obj["models"][0]["config"]["meta"]["semantic_inheritance"]
    inheritance["include"].append("not_in_cdo")
    path.write_text(yaml.safe_dump(obj))
    with pytest.raises(ValueError, match="unknown CDO attributes"):
        compile_semantics(root, registry)
    inheritance["include"].pop()
    inheritance["context"]["columns"]["profit_loss"] = {"data_type": "text"}
    path.write_text(yaml.safe_dump(obj))
    with pytest.raises(ValueError, match="must not override"):
        compile_semantics(root, registry)


def test_governed_metric_requires_included_input(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_c.yml"
    obj = yaml.safe_load(path.read_text())
    inheritance = obj["models"][0]["config"]["meta"]["semantic_inheritance"]
    inheritance["include"].remove("profit_loss")
    path.write_text(yaml.safe_dump(obj))
    with pytest.raises(ValueError, match="requires included attribute"):
        compile_semantics(root, registry)


def test_structured_cdo_uses_compiles_same_contract(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    model = data["models"][0]
    model["config"]["meta"] = {
        "cdo": {
            "uses": "cdo.position",
            "version": 1,
            "include": {
                "attributes": [
                    {"name": "position_id", "entity": {"name": "team_a_position", "type": "primary"}},
                    {"name": "report_date", "dimension": {"type": "time"}, "granularity": "day"},
                    {"name": "profit_loss"},
                    {"name": "instrument_code", "entity": {"name": "instrument", "type": "foreign"}},
                ],
                "metrics": [{"name": "total_profit_loss", "alias": "equity_profit_loss", "label": "Equity Profit and Loss"}],
            },
        }
    }
    model["agg_time_dimension"] = "report_date"
    path.write_text(yaml.safe_dump(data))
    compile_semantics(root, registry)
    result = yaml.safe_load(path.read_text())["models"][0]
    cols = {c["name"]: c for c in result["columns"]}
    assert cols["position_id"]["data_type"] == "text"
    assert cols["position_id"]["entity"]["name"] == "team_a_position"
    assert cols["report_date"]["dimension"]["type"] == "time"
    assert cols["instrument_code"]["entity"]["type"] == "foreign"
    metric = next(x for x in result["metrics"] if x["name"] == "equity_profit_loss")
    assert (metric["agg"], metric["expr"]) == ("sum", "profit_loss")
    assert result["config"]["meta"]["semantic_contract"]["implements"] == "cdo.position"
    assert result["config"]["meta"]["semantic_contract"]["included_metrics"] == ["total_profit_loss"]


def test_structured_cdo_uses_rejects_parent_override(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    model = data["models"][0]
    model["config"]["meta"] = {"cdo": {
        "uses": "cdo.position", "version": 1,
        "include": {"attributes": [{"name": "profit_loss", "data_type": "text"}], "metrics": []}
    }}
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="invalid meta.cdo attribute"):
        compile_semantics(root, registry)


def test_structured_cdo_uses_does_not_affect_independent_models(tmp_path):
    root, registry = project(tmp_path)
    other = root / "models" / "independent.yml"
    before = "version: 2\nmodels:\n  - name: unrelated_model\n"
    other.write_text(before)
    compile_semantics(root, registry)
    assert other.read_text() == before


def test_flat_meta_uses_inherits_same_cdo_contract(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    document = yaml.safe_load(path.read_text())
    model = document["models"][0]
    model["config"]["meta"] = {
        "uses": "cdo.position",
        "version": 1,
        "include": {
            "attributes": [
                {"name": "position_id", "entity": {"name": "team_a_position", "type": "primary"}},
                {"name": "report_date", "dimension": {"type": "time"}, "granularity": "day"},
                {"name": "profit_loss"},
                {"name": "instrument_code", "entity": {"name": "instrument", "type": "foreign"}},
            ],
            "metrics": [
                {"name": "total_profit_loss", "alias": "equity_profit_loss", "label": "Equity Profit and Loss"},
            ],
        },
    }
    model["agg_time_dimension"] = "report_date"
    path.write_text(yaml.safe_dump(document))
    compile_semantics(root, registry)
    compiled = yaml.safe_load(path.read_text())["models"][0]
    assert compiled["config"]["meta"]["semantic_contract"]["implements"] == "cdo.position"
    assert compiled["config"]["meta"]["semantic_contract"]["included_metrics"] == ["total_profit_loss"]
    assert next(m for m in compiled["metrics"] if m["name"] == "equity_profit_loss")["expr"] == "profit_loss"
    assert next(c for c in compiled["columns"] if c["name"] == "position_id")["entity"]["type"] == "primary"


def test_flat_meta_uses_rejects_ambiguous_inheritance(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    document = yaml.safe_load(path.read_text())
    meta = document["models"][0]["config"]["meta"]
    meta.update({"uses": "cdo.position", "version": 1, "include": {"attributes": [], "metrics": []}})
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match="use only one inheritance syntax"):
        compile_semantics(root, registry)


def test_flat_meta_uses_requires_complete_declaration(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    document = yaml.safe_load(path.read_text())
    document["models"][0]["config"]["meta"] = {"uses": "cdo.position", "version": 1}
    path.write_text(yaml.safe_dump(document))
    with pytest.raises(ValueError, match="must define uses, version, and include"):
        compile_semantics(root, registry)


def test_nested_meta_uses_compiles_team_and_preserves_metric_alias(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    model = data["models"][0]
    model["config"]["meta"] = {
        "uses": {"name": "cdo.position", "version": 1},
        "include": {
            "attributes": [
                {"name": "position_id", "entity": {"name": "team_a_position", "type": "primary"}},
                {"name": "report_date", "dimension": {"type": "time"}, "granularity": "day"},
                {"name": "profit_loss"},
                {"name": "instrument_code", "entity": {"name": "instrument", "type": "foreign"}},
            ],
            "metrics": [
                {"name": "total_profit_loss", "alias": "equity_profit_loss", "label": "Equity Profit and Loss"}
            ],
        },
    }
    model["agg_time_dimension"] = "report_date"
    path.write_text(yaml.safe_dump(data))
    assert len(compile_semantics(root, registry)) == 2
    compiled = yaml.safe_load(path.read_text())["models"][0]
    assert compiled["config"]["meta"]["semantic_contract"]["implements"] == "cdo.position"
    assert compiled["config"]["meta"]["semantic_contract"]["version"] == 1
    assert next(x for x in compiled["metrics"] if x["name"] == "equity_profit_loss")["expr"] == "profit_loss"


@pytest.mark.parametrize("bad_reference", [
    {"name": "cdo.position"},
    {"name": "cdo.position", "version": "1"},
    {"name": "cdo.position", "version": 0},
    {"name": "cdo.position", "version": 1, "extra": True},
])
def test_nested_meta_uses_rejects_invalid_parent_reference(tmp_path, bad_reference):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    data["models"][0]["config"]["meta"] = {
        "uses": bad_reference,
        "include": {"attributes": [{"name": "profit_loss"}], "metrics": []},
    }
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="uses must contain exactly|invalid meta.uses reference"):
        compile_semantics(root, registry)


def test_nested_meta_uses_rejects_redundant_top_level_version(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    data["models"][0]["config"]["meta"] = {
        "uses": {"name": "cdo.position", "version": 1},
        "version": 1,
        "include": {"attributes": [{"name": "profit_loss"}], "metrics": []},
    }
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="version belongs inside uses"):
        compile_semantics(root, registry)


def test_attribute_alias_sets_team_semantic_entity_without_renaming_column(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    model = data["models"][0]
    model["config"]["meta"] = {
        "uses": {"name": "cdo.position", "version": 1},
        "include": {
            "attributes": [
                {"name": "position_id", "alias": "equity_position_id",
                 "entity": {"type": "primary"}},
                {"name": "report_date", "dimension": {"type": "time"},
                 "granularity": "day"},
                {"name": "profit_loss"},
                {"name": "instrument_code",
                 "entity": {"name": "instrument", "type": "foreign"}},
            ],
            "metrics": [{"name": "total_profit_loss",
                         "alias": "equity_profit_loss"}],
        },
    }
    model["agg_time_dimension"] = "report_date"
    path.write_text(yaml.safe_dump(data))
    compile_semantics(root, registry)
    compiled = yaml.safe_load(path.read_text())["models"][0]
    columns = {column["name"]: column for column in compiled["columns"]}
    assert "equity_position_id" not in columns
    assert columns["position_id"]["data_type"] == "text"
    assert columns["position_id"]["entity"] == {
        "name": "equity_position_id", "type": "primary"}
    assert compiled["config"]["meta"]["semantic_contract"]["included_attributes"][0] == "position_id"
    assert next(m for m in compiled["metrics"] if m["name"] == "equity_profit_loss")["expr"] == "profit_loss"


def test_attribute_alias_preserves_existing_matching_entity_name(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    data["models"][0]["config"]["meta"] = {
        "uses": {"name": "cdo.position", "version": 1},
        "include": {
            "attributes": [{"name": "position_id", "alias": "equity_position_id",
                            "entity": {"name": "equity_position_id", "type": "primary"}}],
            "metrics": [],
        },
    }
    path.write_text(yaml.safe_dump(data))
    compile_semantics(root, registry)
    result = yaml.safe_load(path.read_text())["models"][0]
    assert result["columns"][0]["entity"]["name"] == "equity_position_id"


@pytest.mark.parametrize("attr,reason", [
    ({"name": "position_id", "alias": "equity_position_id",
      "entity": {"name": "team_a_position", "type": "primary"}}, "conflicts with entity.name"),
    ({"name": "position_id", "alias": "bad-alias",
      "entity": {"type": "primary"}}, "invalid meta attribute alias"),
    ({"name": "position_id", "alias": "equity_position_id"}, "requires exactly one entity or dimension"),
    ({"name": "position_id", "alias": "equity_position_id",
      "entity": {"type": "primary"}, "dimension": {"type": "categorical"}},
     "requires exactly one entity or dimension"),
])
def test_attribute_alias_rejects_ambiguous_or_invalid_spec(tmp_path, attr, reason):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    data["models"][0]["config"]["meta"] = {
        "uses": {"name": "cdo.position", "version": 1},
        "include": {"attributes": [attr], "metrics": []},
    }
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match=reason):
        compile_semantics(root, registry)


def test_attribute_alias_sets_dimension_semantic_name(tmp_path):
    root, registry = project(tmp_path)
    path = root / "models" / "team_a.yml"
    data = yaml.safe_load(path.read_text())
    data["models"][0]["config"]["meta"] = {
        "uses": {"name": "cdo.position", "version": 1},
        "include": {
            "attributes": [{"name": "report_date", "alias": "equity_report_date",
                            "dimension": {"type": "time"}, "granularity": "day"}],
            "metrics": [],
        },
    }
    data["models"][0]["agg_time_dimension"] = "report_date"
    path.write_text(yaml.safe_dump(data))
    compile_semantics(root, registry)
    result = yaml.safe_load(path.read_text())["models"][0]
    assert result["columns"][0]["name"] == "report_date"
    assert result["columns"][0]["dimension"]["name"] == "equity_report_date"
