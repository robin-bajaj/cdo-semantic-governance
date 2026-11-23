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
