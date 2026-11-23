# CDO governance Python toolkit

Installable Python package in `cdo/validator/` (distribution name `dbt-meta-context-validator`, import namespace `meta_context_validator`). Canonical modules are grouped by responsibility:

| Area | Canonical module | Responsibility |
|---|---|---|
| Semantic inheritance | `semantic.inheritance` | Expand `semantic_inheritance.extends` into native dbt YAML |
| Federated composition | `semantic.composition` | Validate Team A/C implementations and create a temporary catalog |
| Native dbt generation | `semantic.dbt_generator` | Produce `cdo_enterprise_positions.sql` and `.yml` |
| CDO contract validation | `validation.contracts` | Validate `manifest.json` against the CDO contract |
| Metric Meta:Context | `validation.metric_context` | Validate metric context, warnings, and expectations |

## Canonical commands

```bash
python -m meta_context_validator.semantic.inheritance --registry <contract.yml> --project .
python -m meta_context_validator.semantic.composition --project . --contract <contract.yml> --manifest target/manifest.json --output /tmp/current_cdo_catalog.yml
python -m meta_context_validator.semantic.dbt_generator --catalog /tmp/current_cdo_catalog.yml --out models/semantic_models/team_cdo/generated
```

The root package retains `cli.py`, `__init__.py`, and no duplicated import compatibility modules. `dbt-mc validate` and `cdo-validate validate` remain supported.

## Installation

From the repository root:

```bash
python -m pip install -e ./cdo/validator
python -m pytest cdo/validator/tests -q
```

## Commands

From a temporary checkout of the federated dbt project:

```bash
python -m meta_context_validator.semantic.inheritance \
  --registry ../contract-validator/cdo/definitions/position_v1.yml \
  --project .

dbt parse --no-partial-parse

python -m meta_context_validator.semantic.composition \
  --project . \
  --contract ../contract-validator/cdo/definitions/position_v1.yml \
  --manifest target/manifest.json \
  --require-semantic-model team_a_equity_positions \
  --require-semantic-model team_c_fi_positions \
  --output /tmp/current_cdo_catalog.yml
```

Generate native CDO artifacts with:

```bash
python -m meta_context_validator.semantic.dbt_generator --catalog /tmp/current_cdo_catalog.yml --out models/semantic_models/team_cdo/generated
```

Both `dbt-mc validate <path>` (existing) and `cdo-validate validate <path>` (new alias) support `--format json` and `--errors-only`. The `--contracts` and `--manifest` options must be supplied together.

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
