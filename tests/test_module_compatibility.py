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


def test_first_party_python_does_not_reference_removed_module_paths():
    """Prevent new imports/CLI calls from resurrecting deleted wrappers."""
    from pathlib import Path
    source_root = Path(__file__).resolve().parents[1]
    obsolete = (
        "cdo_governance.semantic.registry",
        "cdo_governance.semantic.inheritance",
        "cdo_governance.semantic.composition",
        "cdo_governance.semantic.dbt_generator",
        "cdo_governance.validation.contracts",
    )
    for directory in ("src", "tests"):
        for path in (source_root / directory).rglob("*.py"):
            if path.resolve() == Path(__file__).resolve():
                continue
            body = path.read_text(encoding="utf-8")
            for dotted in obsolete:
                assert dotted not in body, f"{path}: still uses {dotted}"
