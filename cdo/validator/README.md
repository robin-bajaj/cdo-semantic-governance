# CDO semantic contract and Meta:Context validator

Python package installed from `cdo/validator/`, providing:

| Component | Module | Purpose |
|---|---|---|
| Semantic inheritance compiler | `meta_context_validator.compile_semantics` | Expand team `semantic_inheritance.extends` to native dbt YAML before parsing |
| Contract validator | `meta_context_validator.contract_rules` | Check the compiled dbt manifest against the CDO registry |
| Metric context validator | `meta_context_validator.rules` | Validate enterprise metric context, expectations, investigations, relationships, and decisions |
| CLI | `dbt-mc validate` | Run context validation with optional contract checks |

## Installation

From the repository root:

```bash
python -m pip install -e ./cdo/validator
python -m pytest cdo/validator/tests -q
```

## Commands

From a temporary checkout of the federated dbt project:

```bash
python -m meta_context_validator.compile_semantics \
  --registry ../contract-validator/cdo/definitions/position_v1.yml \
  --project .

dbt parse --no-partial-parse

python -m meta_context_validator.compose_cdo \
  --project . \
  --contract ../contract-validator/cdo/definitions/position_v1.yml \
  --manifest target/manifest.json \
  --require-semantic-model team_a_equity_positions \
  --require-semantic-model team_c_fi_positions \
  --output generated/cdo/position/v1/cdo_enterprise_positions.yml
```

`dbt-mc validate <path>` supports `--format json` and `--errors-only`. The `--contracts` and `--manifest` options must be supplied together.

The compiler changes model property YAML **in place**. A deployable copy is generated in the federated repository's manual publishing workflow, not committed into the federated source `main` by the compiler.

## Contract behavior

- The **only mandatory attributes source** is the CDO registry's `semantic_columns` list.
- Each opted-in model has a `config.meta.semantic_contract.implements` marker after compilation and must match the contract version.
- Missing columns, declared type mismatches, and `config.contract.enforced: false` are validation errors.
- An unrelated model without the CDO marker is ignored.
- The validator fails if no CDO implementation is present in the manifest it was instructed to validate.
- Native `dbt build` against PostgreSQL, **outside this Python package**, verifies actual SQL relation output and enforced model contracts.

## Optional Metric Meta:Context behavior

The CLI analyzes the `context`, `expectations`, `investigation`, `relationships`, and `decisions` metadata attached to dbt metric definitions. It reports field completeness (Bronze/Silver), structural errors, and false-confidence warnings.

Exit codes for `dbt-mc validate`:

| Exit | Meaning |
|---|---|
| 0 | No blocking metric/context or CDO contract errors |
| 1 | A required metric field, structural check, or CDO contract fails |
| 2 | False-confidence risk detected (e.g. populated thresholds without `decisions.business_rules`) |

For executable examples, see `tests/test_semantic_compiler.py`, `tests/test_independent_projects.py`, and `tests/test_combined_cli.py`.

## Current architecture

See [the repository-level README](../../README.md), [CDO position reference](../README.md), and [central contract](../definitions/position_v1.yml).

This package is a custom **pre-dbt-parse** extension. Its `extends` syntax is not a native dbt feature, and its Meta:Context rules are separate from dbt's native SQL/model contract enforcement.
