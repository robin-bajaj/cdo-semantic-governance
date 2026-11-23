"""Keep old CLI/import paths working while canonical modules are organized."""
from meta_context_validator.semantic.inheritance import compile_semantics as new_compile
from meta_context_validator.semantic.composition import compose_cdo as new_compose
from meta_context_validator.semantic.dbt_generator import generate as new_generate
from meta_context_validator.validation.contracts import validate_cdo_contract as new_contract
from meta_context_validator.validation.metric_context import validate_metric as new_metric

from meta_context_validator.semantic_compiler import compile_semantics as old_compile
from meta_context_validator.compose_cdo import compose_cdo as old_compose
from meta_context_validator.generate_cdo_dbt import generate as old_generate
from meta_context_validator.contract_rules import validate_cdo_contract as old_contract
from meta_context_validator.rules import validate_metric as old_metric


def test_compatibility_exports_point_to_canonical_implementations():
    assert old_compile is new_compile
    assert old_compose is new_compose
    assert old_generate is new_generate
    assert old_contract is new_contract
    assert old_metric is new_metric
