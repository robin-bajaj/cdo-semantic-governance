# CDO Semantic Governance

This repository owns **logical business contracts**, a custom versioned inheritance compiler, CDO validation and the Position composition/generation tools. `cdo.all` is a central **definition registry**, not a physical dbt table or a queryable semantic model. Team A/C own their dbt SQL, semantic entities/dimensions, extra columns and local metrics in the separate [federated dbt repository](https://github.com/robin-bajaj/federated-semantic-poc).

## Repository structure

```text
cdo-semantic-governance/
├── contracts/
│   ├── cdo_all_v1.yml           # cdo.all v1: central business definitions + P&L formula
│   ├── cdo_position_v1.yml      # cdo.position v1: selects from cdo.all
│   └── cdo_counterparty_v1.yml  # cdo.counterparty v1: selects from cdo.all
├── src/cdo_governance/
│   ├── semantic/
│   │   ├── contract_registry.py # Resolve/validate versioned concept dependencies
│   │   ├── semantic_compiler.py # Expand team-authored metadata into native dbt YAML
│   │   ├── position_composer.py # Validate and compose Team A/C Position metadata
│   │   └── position_dbt_generator.py # Generate native CDO Position dbt SQL/YAML
│   └── validation/
│       ├── contract_validator.py # Check compiled model contract compliance
│       └── metric_context.py    # Optional additional metric-governance checks
├── tests/
├── .github/workflows/
├── pyproject.toml
└── README.md
```

## Naming conventions

| Name | Meaning |
| --- | --- |
| `cdo.all` | Enterprise-wide logical definition registry |
| `cdo.position` | Logical Position contract that selects definitions from `cdo.all` |
| `cdo.counterparty` | Logical Counterparty contract that selects definitions from `cdo.all` |
| `cdo_all_v1.yml` | Contract **file** for `cdo.all` version 1 |
| `cdo_position_v1.yml` | Contract **file** for `cdo.position` version 1 |
| `cdo_counterparty_v1.yml` | Contract **file** for `cdo.counterparty` version 1 |
| `total_profit_loss` | Central metric identifier, computed as `SUM(profit_loss)` |
| `profit_loss` | Governed underlying numeric attribute |

Contract filenames follow `<concept_namespace>_<concept_name>_v<version>.yml`. The dotted names in `name:` and `uses:` remain the stable logical identifiers; filenames are merely their locations.

## How inheritance works

```text
cdo.all v1
  ├── cdo.position v1
  │     ├── Team A Equity Position model
  │     └── Team C Fixed Income Position model
  └── cdo.counterparty v1
        (logical concept only; no physical Counterparty dbt model yet)
```

`cdo.all` defines common attributes and the P&L metric **once**. `cdo.position` explicitly selects `position_id`, `report_date`, `profit_loss`, `instrument_code` and `total_profit_loss`. `cdo.counterparty` independently selects `counterparty_id`, `counterparty_name`, and `counterparty_type`.

The Team A/C models opt in with `config.meta.uses: cdo.position`, `version: 1` and `include.attributes`/`include.metrics`. The custom Python compiler resolves the pinned `cdo.position → cdo.all` chain **before** dbt parses the model, then applies the team's entity/dimension mappings and metric aliases. **Native dbt does not implement this custom inheritance mechanism.** An unrelated dbt model without these metadata declarations is left alone.

The recursive registry rejects missing parents, circular dependencies, duplicate contract versions, unknown selected fields, missing metric input attributes, invalid formulas and conflicting definitions. Team model contracts are physically enforced by `dbt build` in configured CI runs. Published contract versions should be treated as immutable and protected through approval and branch policies.

## Local validation

```bash
python -m pip install -e . pytest
python -m cdo_governance.semantic.contract_registry --registry contracts
python -m pytest tests -q
```

When compiling from the **federated** dbt project checkout, supply the **whole contracts directory**, not one leaf contract file:

```bash
python -m cdo_governance.semantic.semantic_compiler \
  --registry ../cdo-governance/contracts \
  --project .

dbt parse --no-partial-parse

python -m cdo_governance.semantic.position_composer \
  --project . \
  --contract ../cdo-governance/contracts \
  --manifest target/manifest.json \
  --require-semantic-model team_a_equity_positions \
  --require-semantic-model team_c_fi_positions \
  --output /tmp/current_cdo_catalog.yml

python -m cdo_governance.semantic.position_dbt_generator \
  --catalog /tmp/current_cdo_catalog.yml \
  --out models/semantic_models/team_cdo/generated
```

The composition catalog is custom metadata, kept **outside** dbt's `models/` directory. The generator emits `cdo_enterprise_positions.sql` and `cdo_enterprise_positions.yml` for the Position union of Team A/C. The generated CDO metric derives its formula from the resolved contract rather than redefining it.

## Release boundaries

The governance CI validates the registry and regression tests. The federated CI checks Team A/C inheritance, native dbt parsing and database contracts in an isolated schema. The separate protected promotion workflow compiles the approved main branch, composes the Position catalog, generates and builds the native CDO SQL/YAML, then commits outputs to `generated/production`. dbt Cloud deployment remains a separate manual step.

The `cdo.counterparty` contract is intentionally **logical only**. It does not create a physical table, automatically create a Position–Counterparty join or alter the existing enterprise Position model. Exposing Counterparty in a BI tool requires an independent team implementation and explicit semantic relationships.


## Canonical Python modules

Only the documented implementation modules are supported: `cdo_governance.semantic.contract_registry`, `cdo_governance.semantic.semantic_compiler`, `cdo_governance.semantic.position_composer`, `cdo_governance.semantic.position_dbt_generator`, and `cdo_governance.validation.contract_validator`. Legacy module shims (`semantic.registry`, `semantic.inheritance`, `semantic.composition`, `semantic.dbt_generator`, and `validation.contracts`) were removed after migrating the known federated CI and promotion workflows.

**Breaking change:** External consumers still importing or invoking those old paths must migrate to the canonical names. The separately maintained metric-context validator and the existing `dbt-mc` CLI alias are not part of this removal.
