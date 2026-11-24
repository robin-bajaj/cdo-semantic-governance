"""Canonical CDO Python module entrypoints remain available after shim removal."""
import importlib
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module,attribute", [
    ("semantic.contract_registry", "load_registry"),
    ("semantic.semantic_compiler", "compile_semantics"),
    ("semantic.position_composer", "compose_cdo"),
    ("semantic.position_dbt_generator", "generate"),
    ("validation.contract_validator", "validate_cdo_contract"),
])
def test_canonical_modules_export_api(module, attribute):
    implementation = importlib.import_module(f"cdo_governance.{module}")
    assert callable(getattr(implementation, attribute))


@pytest.mark.parametrize("module", [
    "semantic.contract_registry",
    "semantic.semantic_compiler",
    "semantic.position_composer",
    "semantic.position_dbt_generator",
])
def test_canonical_module_cli_help(module):
    result = subprocess.run(
        [sys.executable, "-m", f"cdo_governance.{module}", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
