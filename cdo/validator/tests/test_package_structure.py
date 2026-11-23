"""Canonical CDO module smoke tests; no duplicate public compatibility modules."""
import importlib

from meta_context_validator.semantic.inheritance import compile_semantics, main as compile_main
from meta_context_validator.semantic.composition import compose_cdo, main as compose_main
from meta_context_validator.semantic.dbt_generator import generate, main as generate_main
from meta_context_validator.validation.contracts import validate_cdo_contract
from meta_context_validator.validation.metric_context import validate_metric


def test_canonical_modules_export_entrypoints():
    for callable_api in (compile_semantics, compile_main, compose_cdo, compose_main,
                         generate, generate_main, validate_cdo_contract, validate_metric):
        assert callable(callable_api)


def test_canonical_modules_are_importable():
    for path in ("semantic.inheritance", "semantic.composition",
                 "semantic.dbt_generator", "validation.contracts", "validation.metric_context"):
        assert importlib.import_module("meta_context_validator." + path)


def test_inheritance_cli_passes_project_before_registry(monkeypatch):
    """CLI flags should map to compile_semantics(project_path, registry_path)."""
    import sys
    from pathlib import Path
    import meta_context_validator.semantic.inheritance as inheritance

    observed = {}

    def fake_compile(project, registry):
        observed["project"] = project
        observed["registry"] = registry
        return ["models/team_a.yml", "models/team_c.yml"]

    monkeypatch.setattr(inheritance, "compile_semantics", fake_compile)
    monkeypatch.setattr(sys, "argv", ["inheritance", "--registry", "contract.yml", "--project", "dbt-project"])
    inheritance.main()
    assert observed == {"project": Path("dbt-project"), "registry": Path("contract.yml")}
