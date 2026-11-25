"""Contract graph tests: provenance, safe versioning, and fail-closed inheritance."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from cdo_governance.semantic.contract_registry import load_registry, resolve_contract
from cdo_governance.semantic.semantic_compiler import compile_semantics
from cdo_governance.semantic.position_composer import compose_cdo
from test_compose_cdo import setup_compiled


HERE = Path(__file__).resolve().parents[1] / "contracts"


def test_registry_resolves_position_and_counterparty_without_duplication():
    definitions = load_registry(HERE)
    position = definitions[("cdo.position", "1")]
    counterparty = definitions[("cdo.counterparty", "1")]
    all_definitions = definitions[("cdo.all", "1")]
    assert [a["name"] for a in position["attributes"]] == [
        "position_id", "report_date", "profit_loss", "instrument_code"]
    assert [m["name"] for m in position["metrics"]] == ["total_profit_loss"]
    assert position["metrics"][0]["expr"] == "profit_loss"
    assert position["metrics"][0]["fill_nulls_with"] == 0
    assert [a["name"] for a in counterparty["attributes"]] == [
        "counterparty_id", "counterparty_name", "counterparty_type"]
    assert counterparty["metrics"] == []
    assert counterparty["lineage"] == [{"name": "cdo.all", "version": 1}]
    assert position["lineage"] == [{"name": "cdo.all", "version": 1}]
    shared = {a["name"]: a for a in all_definitions["attributes"]}
    assert position["attributes"][3] == shared["instrument_code"]


def test_modifying_resolved_child_does_not_mutate_parent():
    graph = load_registry(HERE)
    graph[("cdo.position", "1")]["attributes"][0]["data_type"] = "broken"
    assert graph[("cdo.all", "1")]["attributes"][0]["data_type"] == "text"


def test_recursive_graph_supports_more_than_two_levels(tmp_path):
    all_spec = yaml.safe_load((HERE / "cdo_all_v1.yml").read_text())
    position = yaml.safe_load((HERE / "cdo_position_v1.yml").read_text())
    child = {
        "name": "cdo.equity", "version": 1,
        "uses": {"name": "cdo.position", "version": 1},
        "include": {"attributes": ["position_id", "profit_loss"],
                    "metrics": ["total_profit_loss"]},
    }
    for filename, spec in [("all.yml", all_spec), ("position.yml", position),
                           ("equity.yml", child)]:
        (tmp_path / filename).write_text(yaml.safe_dump(spec))
    resolved = resolve_contract(tmp_path, "cdo.equity", 1)
    assert resolved["lineage"] == [
        {"name": "cdo.all", "version": 1},
        {"name": "cdo.position", "version": 1},
    ]
    assert resolved["metrics"][0]["expr"] == "profit_loss"


def test_unknown_parent_fails_closed(tmp_path):
    leaf = yaml.safe_load((HERE / "cdo_position_v1.yml").read_text())
    (tmp_path / "position.yml").write_text(yaml.safe_dump(leaf))
    with pytest.raises(ValueError, match="Missing CDO parent/version"):
        load_registry(tmp_path)


def test_rejects_unknown_inherited_attribute(tmp_path):
    parent = yaml.safe_load((HERE / "cdo_all_v1.yml").read_text())
    child = yaml.safe_load((HERE / "cdo_position_v1.yml").read_text())
    child["include"]["attributes"].append("unapproved_new_field")
    (tmp_path / "all.yml").write_text(yaml.safe_dump(parent))
    (tmp_path / "position.yml").write_text(yaml.safe_dump(child))
    with pytest.raises(ValueError, match="unknown inherited attributes"):
        load_registry(tmp_path)


def test_rejects_metric_missing_its_included_input(tmp_path):
    parent = yaml.safe_load((HERE / "cdo_all_v1.yml").read_text())
    child = yaml.safe_load((HERE / "cdo_position_v1.yml").read_text())
    child["include"]["attributes"].remove("profit_loss")
    (tmp_path / "all.yml").write_text(yaml.safe_dump(parent))
    (tmp_path / "position.yml").write_text(yaml.safe_dump(child))
    with pytest.raises(ValueError, match="metric total_profit_loss references"):
        load_registry(tmp_path)


def test_rejects_circular_inheritance(tmp_path):
    a = {"name": "cdo.a", "version": 1, "uses": {"name": "cdo.b", "version": 1},
         "include": {"attributes": ["position_id"], "metrics": []}}
    b = {"name": "cdo.b", "version": 1, "uses": {"name": "cdo.a", "version": 1},
         "include": {"attributes": ["position_id"], "metrics": []}}
    for spec in (a, b):
        (tmp_path / (spec["name"] + ".yml")).write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError, match="Circular CDO inheritance"):
        load_registry(tmp_path)


def test_rejects_duplicate_concept_versions(tmp_path):
    original = yaml.safe_load((HERE / "cdo_all_v1.yml").read_text())
    for name in ("a.yml", "b.yml"):
        (tmp_path / name).write_text(yaml.safe_dump(original))
    with pytest.raises(ValueError, match="duplicate CDO contract"):
        load_registry(tmp_path)


def test_legacy_complete_definition_still_supported(tmp_path):
    complete = {
        "name": "cdo.position", "version": 1,
        "attributes": [{"name": "position_id", "data_type": "text",
                        "description": "Position ID"}],
        "metrics": [],
    }
    path = tmp_path / "position.yml"
    path.write_text(yaml.safe_dump(complete))
    assert resolve_contract(path, "cdo.position", 1)["attributes"][0]["name"] == "position_id"


def test_existing_team_compilation_and_composition_accept_resolved_registry(tmp_path):
    # The established fixture uses a standalone position file. Replace it with
    # the graph and confirm Team A/C still compile without altering their DSL.
    root, original, manifest = setup_compiled(tmp_path / "original")
    # setup_compiled produces an already compiled project: verify catalog uses
    # registry-resolved definitions and includes lineage.
    result_file = tmp_path / "catalog.yml"
    compose_cdo(root, original, manifest, result_file, bindings_path=root.parent / 'bindings.yml')
    baseline = yaml.safe_load(result_file.read_text())
    assert baseline["contract"] == {"name": "cdo.position", "version": 1}
    # Fresh project with uncompiled team models using the registry.
    from test_semantic_compiler import project
    fresh_root, _ = project(tmp_path / "fresh")
    assert len(compile_semantics(fresh_root, HERE, fresh_root.parent / 'bindings.yml')) == 2
    for team in ("team_a", "team_c"):
        model = yaml.safe_load((fresh_root / "models" / f"{team}.yml").read_text())["models"][0]
        assert "meta" not in model["config"]
        resolved = yaml.safe_load((fresh_root.parent / "bindings.yml").read_text())
        assert resolved["models"][f"stg_{team}_positions"]["semantic_contract"]["implements"] == "cdo.position"
        assert model["metrics"][0]["expr"] == "profit_loss"


def test_checked_in_contract_filenames_match_logical_names_and_versions():
    """A published contract's path should identify its dotted name and version."""
    for path in sorted(HERE.glob("*.yml")) + sorted(HERE.glob("*.yaml")):
        contract = yaml.safe_load(path.read_text())
        expected = contract["name"].replace(".", "_") + f"_v{contract['version']}" + path.suffix
        assert path.name == expected, f"{path.name} should be {expected}"


def test_nested_parent_reference_is_valid_in_both_cdo_concepts():
    for filename in ("cdo_position_v1.yml", "cdo_counterparty_v1.yml"):
        data = yaml.safe_load((HERE / filename).read_text())
        assert data["uses"] == {"name": "cdo.all", "version": 1}
        assert "uses_version" not in data


@pytest.mark.parametrize("bad_reference", [
    {"name": "cdo.all"},
    {"name": "cdo.all", "version": "1"},
    {"name": "cdo.all", "version": 0},
    {"name": "cdo.all", "version": 1, "extra": True},
])
def test_nested_parent_reference_rejects_invalid_metadata(tmp_path, bad_reference):
    parent = yaml.safe_load((HERE / "cdo_all_v1.yml").read_text())
    child = yaml.safe_load((HERE / "cdo_position_v1.yml").read_text())
    child["uses"] = bad_reference
    (tmp_path / "all.yml").write_text(yaml.safe_dump(parent))
    (tmp_path / "position.yml").write_text(yaml.safe_dump(child))
    with pytest.raises(ValueError, match="invalid parent reference|uses must contain exactly"):
        load_registry(tmp_path)


def test_nested_parent_reference_rejects_mixed_legacy_version(tmp_path):
    parent = yaml.safe_load((HERE / "cdo_all_v1.yml").read_text())
    child = yaml.safe_load((HERE / "cdo_position_v1.yml").read_text())
    child["uses_version"] = 1
    (tmp_path / "all.yml").write_text(yaml.safe_dump(parent))
    (tmp_path / "position.yml").write_text(yaml.safe_dump(child))
    with pytest.raises(ValueError, match="invalid inherited-contract structure"):
        load_registry(tmp_path)
