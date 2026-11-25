"""Canonical CDO module entrypoint smoke tests."""
import importlib

from cdo_governance.semantic.semantic_compiler import compile_semantics, main as compile_main
from cdo_governance.semantic.position_composer import compose_cdo, main as compose_main
from cdo_governance.semantic.position_dbt_generator import generate, main as generate_main
from cdo_governance.validation.contract_validator import validate_cdo_contract
from cdo_governance.validation.metric_context import validate_metric


def test_canonical_modules_export_entrypoints():
    for callable_api in (compile_semantics, compile_main, compose_cdo, compose_main,
                         generate, generate_main, validate_cdo_contract, validate_metric):
        assert callable(callable_api)


def test_canonical_modules_are_importable():
    for path in ("semantic.semantic_compiler", "semantic.position_composer",
                 "semantic.position_dbt_generator", "validation.contract_validator", "validation.metric_context"):
        assert importlib.import_module("cdo_governance." + path)


def test_inheritance_cli_passes_project_before_registry(monkeypatch):
    """CLI flags should map to compile_semantics(project_path, registry_path)."""
    import sys
    from pathlib import Path
    import cdo_governance.semantic.semantic_compiler as inheritance

    observed = {}

    def fake_compile(project, registry, bindings_output=None):
        observed["project"] = project
        observed["registry"] = registry
        observed["bindings_output"] = bindings_output
        return ["models/team_a.yml", "models/team_c.yml"]

    monkeypatch.setattr(inheritance, "compile_semantics", fake_compile)
    monkeypatch.setattr(sys, "argv", ["semantic_compiler", "--registry", "contract.yml", "--project", "dbt-project"])
    inheritance.main()
    assert observed == {"project": Path("dbt-project"), "registry": Path("contract.yml"), "bindings_output": None}
