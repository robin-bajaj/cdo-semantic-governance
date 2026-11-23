# CDO Semantic Governance

The CDO owns the canonical Position interface, semantic inheritance rules, Team A/C composition, native dbt SQL/YAML generation, and contract/metric validation. This package provides a custom pre-dbt-parse extension; `semantic_inheritance.extends` is **not native dbt**.

## Repository layout

```text
cdo-semantic-governance/
├── contracts/
│   └── position_v1.yml
├── src/
│   └── cdo_governance/
│       ├── __init__.py
│       ├── cli.py
│       ├── semantic/
│       │   ├── __init__.py
│       │   ├── inheritance.py
│       │   ├── composition.py
│       │   └── dbt_generator.py
│       └── validation/
│           ├── __init__.py
│           ├── contracts.py
│           └── metric_context.py
├── tests/
├── .github/workflows/governance-ci.yml
├── pyproject.toml
└── README.md
```

## Ownership and data flow

- **`contracts/position_v1.yml`**: CDO-governed interface (position_id, report_date, profit_loss, instrument_code), types, entities and `SUM(profit_loss)` semantics.
- **`semantic/inheritance.py`**: expands participating Team A/C authored YAML to native dbt properties in a disposable working copy.
- **`validation/contracts.py`**: checks the compiled dbt manifest against the contract. Non-participating team models remain outside this contract.
- **`semantic/composition.py`**: composes validated Team A and Team C definitions into a custom catalog, preserving local extensions and aliases.
- **`semantic/dbt_generator.py`**: generates native `cdo_enterprise_positions.sql` and `.yml` from the catalog.
- **`validation/metric_context.py`**: optional Meta:Context metric checks, also available through `cdo-validate` / `dbt-mc`.

All generated files belong to the federated dbt project's `generated/production` branch, not to this source repository. The inspectable custom composition catalog is kept at `artifacts/cdo/position_v1_composition.yml` outside dbt's `models/` directory.

## Installation and tests

```bash
python -m pip install -e . pytest
python -m pytest tests -q
```

The `governance-ci.yml` workflow runs these tests on PRs and pushes to `main`. It verifies governance code independently of the federated dbt repository, which pins an approved governance commit.

## CLI from a disposable federated dbt project checkout

Assuming this repository is checked out at `../contract-validator`:

```bash
python -m cdo_governance.semantic.inheritance \
  --registry ../contract-validator/contracts/position_v1.yml \
  --project .

dbt parse --no-partial-parse

python -m cdo_governance.semantic.composition \
  --project . \
  --contract ../contract-validator/contracts/position_v1.yml \
  --manifest target/manifest.json \
  --require-semantic-model team_a_equity_positions \
  --require-semantic-model team_c_fi_positions \
  --output /tmp/current_cdo_catalog.yml

python -m cdo_governance.semantic.dbt_generator \
  --catalog /tmp/current_cdo_catalog.yml \
  --out models/semantic_models/team_cdo/generated
```

`compose_cdo` refuses to emit the custom catalog inside `models/` because it is not native dbt syntax.

## Deployment boundary

Team A/C PRs run validation-only CI in the federated repository. A human-approved merge from `main` into `generated/production` triggers the consolidated promotion job: compile, compose, generate native CDO SQL/YAML, parse, build on Neon, and commit compiled Team A/C plus CDO outputs and custom catalog to the deployment branch. The hosted dbt Cloud deployment remains a separate action. Changes to this governance package must be promoted by explicitly updating the pinned revision used in federated CI and promotion.
