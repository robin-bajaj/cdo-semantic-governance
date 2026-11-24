# CDO Semantic Governance

The CDO owns reusable Position business attribute names, types and descriptions, plus governed metric formulas. Teams own dbt entity/dimension context and explicitly select the business attributes they use. The governance package handles inheritance, composition, native dbt SQL/YAML generation and validation. This package provides a custom pre-dbt-parse extension; `semantic_inheritance.extends` is **not native dbt**.

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

- **`contracts/position_v1.yml`**: central business dictionary containing only `name`, `data_type`, and `description` for each attribute. Its governed `cdo.profit_loss` metric stays in this same file.
- **Team-owned `semantic_inheritance.include`**: explicit whitelist of the CDO attributes to inherit. Newly registered attributes never appear in a team model unless the team opts in.
- **Team-owned `semantic_inheritance.context`**: semantic entity/dimension/granularity and aggregation-time mappings, not part of the CDO attribute dictionary.
- **`semantic/inheritance.py`**: merges the selected governed attributes with local contextual roles and appends team-owned extensions/metrics. Blocks type/description overrides and unknown or duplicate selections.
- **`validation/contracts.py`**: checks the declared selected CDO attributes and their types in the compiled manifest. Native dbt model contracts may still be required.
- **`semantic/composition.py`**: records each participating team's selected attributes and its contextual mappings in a custom composition catalog.
- **`semantic/dbt_generator.py`**: creates a native composite SQL/YAML model. The current enterprise Position view requires `position_id`, `report_date`, and `profit_loss` in each team; optional included attributes are typed-NULL-padded for teams that omit them.
- **`validation/metric_context.py`**: optional metric governance checks.

Generated files live in the federated dbt project's `generated/production` branch, including the inspectable `artifacts/cdo/position_v1_composition.yml` outside dbt's `models/`.

## Team authoring example

```yaml
semantic_inheritance:
  extends: cdo.position
  version: 1
  include: [position_id, report_date, profit_loss, instrument_code]
  context:
    agg_time_dimension: report_date
    columns:
      position_id:
        entity: {name: team_a_position, type: primary}
      report_date:
        dimension: {type: time}
        granularity: day
      instrument_code:
        entity: {name: instrument, type: foreign}
  metric_aliases:
    cdo.profit_loss: equity_profit_loss
```

The governed P&L metric remains in `position_v1.yml`. Selecting that metric requires the team to include `profit_loss`. The exact attribute whitelist can differ across teams; the composite model's three core fields remain required.

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


## Multi-level CDO business contracts

The `contracts/` directory is a versioned **logical business registry**, not a set of dbt models or physical tables.

- `all_v1.yml` (`cdo.all`) defines the centralized Position fields, Counterparty fields, and the governed `total_profit_loss = SUM(profit_loss)` metric.
- `position_v1.yml` (`cdo.position`) selects its four Position fields and the metric from `cdo.all` v1; it no longer duplicates definitions.
- `counterparty_v1.yml` (`cdo.counterparty`) selects counterparty fields from the same dictionary. No physical Counterparty staging SQL, semantic join, or metric is implied.
- Team A/C continue to author `config.meta.uses: cdo.position` without referring to `cdo.all` directly.

The Python compiler fully resolves recursive `uses` + `uses_version` dependencies before expanding team models. Every concept selects `include.attributes` and `include.metrics` explicitly. Duplicate versions, dangling parents, cycles, unsupported overrides, unknown selected fields, missing metric inputs, and invalid flat metrics fail closed. The compiled team metadata includes the version-pinned parent lineage. Other models without an inheritance declaration remain independent.

To validate the entire registry:

```bash
python -m cdo_governance.semantic.registry --registry contracts
python -m pytest tests -q
```

For the normal team compilation and Position composition workflows, pass the **directory** rather than the old single-file Position contract:

```bash
python -m cdo_governance.semantic.inheritance --registry /path/to/contracts --project .
python -m cdo_governance.semantic.composition --project . --contract /path/to/contracts --manifest target/manifest.json --output /tmp/current_cdo_catalog.yml
```

**Versioning policy:** Treat published contract versions as immutable in review; a breaking change requires a new version and explicit adoption. Enforce this policy with protected branches and mandatory checks in the owning repository. This implementation validates structural references but does not independently prevent an authorized maintainer from editing an old version.

**Scope boundary:** The Counterparty contract demonstrates reusable business definitions. Exposing a queryable Counterparty semantic model or joining Position to Counterparty requires separately owned staging SQL, an entity relationship, corresponding database tests, and an approved dbt deployment; none are silently generated by logical inheritance.
