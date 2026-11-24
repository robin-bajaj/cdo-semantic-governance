"""Validate descriptive public modules and backwards-compatible old paths.

The federated POC pins governance commits, but existing project integrations
may still import or execute the historical module names.
"""
import importlib
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("old,new,attribute", [
    ("semantic.registry", "semantic.contract_registry", "load_registry"),
    ("semantic.inheritance", "semantic.semantic_compiler", "compile_semantics"),
    ("semantic.composition", "semantic.position_composer", "compose_cdo"),
    ("semantic.dbt_generator", "semantic.position_dbt_generator", "generate"),
    ("validation.contracts", "validation.contract_validator", "validate_cdo_contract"),
])
def test_legacy_module_reexports_new_implementation(old, new, attribute):
    before = importlib.import_module(f"cdo_governance.{old}")
    after = importlib.import_module(f"cdo_governance.{new}")
    assert getattr(before, attribute) is getattr(after, attribute)


@pytest.mark.parametrize("module", [
    "semantic.contract_registry",
    "semantic.semantic_compiler",
    "semantic.position_composer",
    "semantic.position_dbt_generator",
    "semantic.registry",
    "semantic.inheritance",
    "semantic.composition",
    "semantic.dbt_generator",
])
def test_module_cli_still_supports_help(module):
    result = subprocess.run(
        [sys.executable, "-m", f"cdo_governance.{module}", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
