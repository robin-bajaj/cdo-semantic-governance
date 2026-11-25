"""End-to-end selections over validated Team A/C composition fixtures."""
from copy import deepcopy
import yaml
import pytest
from test_compose_cdo import setup_compiled
from cdo_governance.semantic.position_composer import compose_cdo
from cdo_governance.semantic.position_selection import (
    available_implementations, select_composition)
from cdo_governance.semantic.position_dbt_generator import generate


def make_catalog(tmp_path):
    root, contract, manifest = setup_compiled(tmp_path)
    path = tmp_path / "all_catalog.yml"
    compose_cdo(root, contract, manifest, path,
                bindings_path=root.parent / "bindings.yml")
    return yaml.safe_load(path.read_text())


def choice(catalog, name="team_a_positions", attributes=None, metrics=None):
    return {
        "name": catalog["name"], "contract": deepcopy(catalog["contract"]),
        "sources": [{
            "semantic_model": name, "source_team": "TEAM_A",
            "include": {
                "attributes": attributes or ["position_id", "report_date", "profit_loss", "mtm"],
                "metrics": metrics if metrics is not None else [],
            },
        }],
        "enterprise_metrics": ["cdo_total_profit_loss"],
    }


def apply(tmp_path, catalog, selection):
    file = tmp_path / "selection.yml"
    file.write_text(yaml.safe_dump(selection))
    return select_composition(catalog, file)


def test_discovery_only_lists_validated_models_fields_and_eligible_metrics(tmp_path):
    catalog = make_catalog(tmp_path)
    discovered = available_implementations(catalog)
    assert discovered["contract"]["name"] == "cdo.position"
    choices = {i["semantic_model"]: i for i in discovered["available_implementations"]}
    assert set(choices) == {"team_a_positions", "team_c_positions"}
    assert "mtm" in choices["team_a_positions"]["attributes"]
    assert "team_a_profit_loss" in choices["team_a_positions"]["metrics"]



def test_discovery_reports_team_entity_and_dimension_aliases_without_changing_columns(tmp_path):
    catalog = make_catalog(tmp_path)
    a = next(i for i in catalog["implementations"] if i["semantic_model"] == "team_a_positions")
    c = next(i for i in catalog["implementations"] if i["semantic_model"] == "team_c_positions")
    a_column = next(x for x in a["columns"] if x["name"] == "position_id")
    c_column = next(x for x in c["columns"] if x["name"] == "position_id")
    a_column["entity"] = {"name": "equity_position_id", "type": "primary"}
    c_column["entity"] = {"name": "team_c_position", "type": "primary"}
    date = next(x for x in a["columns"] if x["name"] == "report_date")
    date["dimension"] = {"name": "equity_report_date", "type": "time"}
    date["granularity"] = "day"
    discovered = available_implementations(catalog)
    choices = {x["semantic_model"]: x for x in discovered["available_implementations"]}
    team_a = {x["name"]: x for x in choices["team_a_positions"]["attribute_semantics"]}
    team_c = {x["name"]: x for x in choices["team_c_positions"]["attribute_semantics"]}
    assert team_a["position_id"] == {
        "name": "position_id", "data_type": "text",
        "semantic_entity": "equity_position_id", "entity_type": "primary"}
    assert team_c["position_id"]["semantic_entity"] == "team_c_position"
    assert team_a["report_date"]["semantic_dimension"] == "equity_report_date"
    assert team_a["report_date"]["dimension_type"] == "time"
    assert team_a["report_date"]["granularity"] == "day"
    assert team_a["mtm"] == {"name": "mtm", "data_type": "numeric"}
    assert "position_id" in choices["team_a_positions"]["attributes"]
    assert "equity_position_id" not in choices["team_a_positions"]["attributes"]

    # Selection continues to use the governed column, not a team semantic alias.
    chosen = choice(catalog)
    assert apply(tmp_path, catalog, chosen)["implementations"][0]["columns"][0]["name"] == "position_id"
    chosen["sources"][0]["include"]["attributes"][0] = "equity_position_id"
    with pytest.raises(ValueError, match="not available"):
        apply(tmp_path, catalog, chosen)


def test_discovery_falls_back_to_column_name_for_unaliased_semantic_role(tmp_path):
    catalog = make_catalog(tmp_path)
    discovered = available_implementations(catalog)
    team_a = next(x for x in discovered["available_implementations"]
                  if x["semantic_model"] == "team_a_positions")
    attributes = {x["name"]: x for x in team_a["attribute_semantics"]}
    assert attributes["report_date"]["semantic_dimension"] == "report_date"
    assert attributes["position_id"]["semantic_entity"] == "team_a_position"

def test_pick_only_team_a_and_only_selected_fields_and_metric(tmp_path):
    catalog = make_catalog(tmp_path)
    selection = choice(catalog, metrics=["team_a_profit_loss"])
    picked = apply(tmp_path, catalog, selection)
    assert len(picked["implementations"]) == 1
    assert picked["common_attributes"] == ["position_id", "report_date", "profit_loss"]
    assert [c["name"] for c in picked["implementations"][0]["columns"]] == [
        "position_id", "report_date", "profit_loss", "mtm"]
    out = tmp_path / "generated"
    generate_file = tmp_path / "selected_catalog.yml"
    generate_file.write_text(yaml.safe_dump(picked))
    generate(generate_file, out)
    sql = (out / "cdo_enterprise_positions.sql").read_text()
    generated = yaml.safe_load((out / "cdo_enterprise_positions.yml").read_text())["models"][0]
    assert "stg_team_a_positions" in sql
    assert "stg_team_c_positions" not in sql
    assert "mtm::numeric as mtm" in sql
    assert "cash" not in sql
    assert "instrument_code" not in sql
    assert "meta" not in generated.get("config", {})
    assert {m["name"] for m in generated["metrics"]} == {
        "cdo_total_profit_loss", "cdo_team_a_profit_loss"}


def test_excluded_model_or_metric_not_published(tmp_path):
    catalog = make_catalog(tmp_path)
    selection = choice(catalog, metrics=[])
    selection["enterprise_metrics"] = ["cdo_position_row_count"]
    picked = apply(tmp_path, catalog, selection)
    file = tmp_path / "catalog.yml"
    file.write_text(yaml.safe_dump(picked))
    output = tmp_path / "out"
    generate(file, output)
    native = yaml.safe_load((output / "cdo_enterprise_positions.yml").read_text())["models"][0]
    assert [m["name"] for m in native["metrics"]] == ["cdo_position_row_count"]


@pytest.mark.parametrize("change,expected", [
    (lambda s: s["sources"][0].update(semantic_model="unknown_model"), "Unvalidated"),
    (lambda s: s["sources"][0]["include"]["attributes"].remove("profit_loss"), "required core"),
    (lambda s: s["sources"][0]["include"]["metrics"].append("unknown_metric"), "not found"),
    (lambda s: s["sources"][0]["include"]["metrics"].append("team_a_profit_loss") or
     s["sources"][0]["include"]["attributes"].remove("profit_loss"), "required core"),
    (lambda s: s.update(contract={"name": "cdo.position", "version": 2}), "contract version"),
])
def test_selection_fails_closed(tmp_path, change, expected):
    catalog = make_catalog(tmp_path)
    selection = choice(catalog)
    change(selection)
    with pytest.raises(ValueError, match=expected):
        apply(tmp_path, catalog, selection)


def test_selected_metric_requires_its_field(tmp_path):
    catalog = make_catalog(tmp_path)
    selection = choice(catalog, attributes=["position_id","report_date","profit_loss"],
                       metrics=["team_a_profit_loss"])
    # profit_loss present, so inherited metric selection is valid.
    assert apply(tmp_path, catalog, selection)["implementations"][0]["metrics"][0]["name"] == "team_a_profit_loss"
    selection["sources"][0]["include"]["metrics"] = ["team_a_count"]
    assert apply(tmp_path, catalog, selection)["implementations"][0]["metrics"][0]["name"] == "team_a_count"


def test_selection_rejects_unsupported_metric_and_type_mismatch(tmp_path):
    catalog = make_catalog(tmp_path)
    selection = choice(catalog, metrics=["team_a_profit_loss"])
    impl = next(i for i in catalog["implementations"] if i["semantic_model"] == "team_a_positions")
    impl["metrics"][0]["filter"] = "source_team = 'TEAM_A'"
    with pytest.raises(ValueError, match="unsupported"):
        apply(tmp_path, catalog, selection)
