# CDO Semantic Contract Validator

Centralized **CDO-owned semantic contracts, inheritance compilation, and governance validation** for the Federated dbt POC.

The CDO publishes a custom, versioned business definition independently of the teams' physical SQL models. Team A and Team C opt in through `config.meta.semantic_inheritance`. A pre-parse compiler translates this custom declaration into native dbt model properties, metrics, and a contract implementation marker. dbt itself **does not natively support** our `semantic_inheritance.extends` syntax.

## Repository layout

```text
cdo/
├── definitions/
│   └── position_v1.yml                # CDO-owned contract (source of truth)
└── validator/                         # Installable Python governance toolkit
    ├── pyproject.toml
    ├── meta_context_validator/
    │   ├── semantic/
    │   │   ├── inheritance.py         # Compile opt-in team semantic inheritance
    │   │   ├── composition.py         # Compose validated team catalog
    │   │   └── dbt_generator.py       # Generate native CDO SQL and YAML
    │   ├── validation/
    │   │   ├── contracts.py           # Enforce CDO Position interface
    │   │   └── metric_context.py      # Metric Meta:Context rules
    │   ├── cli.py                     # Validation CLI
    │   ├── compile_semantics.py       # Existing python -m command
    │   ├── compose_cdo.py             # Existing python -m command (compatibility)
    │   ├── generate_cdo_dbt.py        # Existing python -m command (compatibility)
    │   ├── semantic_compiler.py       # Legacy import compatibility
    │   ├── contract_rules.py          # Legacy import compatibility
    │   └── rules.py                   # Legacy import compatibility
    └── tests/                         # Regression & backward compatibility tests
.github/workflows/validator-tests.yml   # CI
```

The new `semantic/` and `validation/` directories contain the implementations. The thin root modules preserve **existing** imports, `python -m` commands, and the `dbt-mc` CLI so currently pinned federated workflows remain compatible.

## The CDO Position contract

The single source of truth is [`cdo/definitions/position_v1.yml`](cdo/definitions/position_v1.yml).

- Contract: `cdo.position`, version `1`; owner: CDO.
- **`semantic_columns` is canonical**: required names, data types, entity and dimension roles are all declared in this one list; there is no separate `required_columns` mapping.
- Required attributes: `position_id` (text), `report_date` (date/time dimension), `profit_loss` (numeric), `instrument_code` (integer).
- Governed metric: `cdo.profit_loss` = `SUM(profit_loss)`; teams use independent aliases.
- `require_native_contract: true`: participating models must enable `config.contract.enforced: true`.

CDO governs the **interface and aggregation semantics**, not whether upstream P&L values are financially correct.

## How Team A/C consumes the definition

In the [Federated dbt POC](https://github.com/robin-bajaj/federated-semantic-poc), Team A/C source YAML contains a short opt-in declaration (abridged):

```yaml
models:
  - name: stg_team_a_positions
    config:
      contract:
        enforced: true
      meta:
        semantic_inheritance:
          extends: cdo.position
          version: 1
          entity_aliases:
            position: team_a_position
          metric_aliases:
            cdo.profit_loss: equity_profit_loss
    semantic_model:
      enabled: true
```

The compiler expands this to the inherited column definitions, semantic entities/dimensions, and metric formula before dbt parses the project; it also adds `config.meta.semantic_contract` with `implements: cdo.position` and `version: 1`. Team-local extra columns and metrics are allowed but cannot redeclare inherited names. Models without the `semantic_inheritance` opt-in are unchanged by the compiler and are not subjected to the CDO Position contract by the manifest validator.

## CI and promotion

**Governance repository:** `validator-tests.yml` installs the package and runs its test suite whenever the governance repository changes.

**Federated repository:** Team A/C PRs to `main` run validation-only CI: compile inherited semantics, verify contracts and dbt parsing, and build staging models with native enforced contracts in an isolated Neon schema for eligible PRs. This does **not** generate or publish CDO snapshots.

**Promotion:** A manually approved merge from federated `main` into `generated/production` triggers the consolidated promotion workflow (or a manual run on `main` can bootstrap a missing production branch). Promotion uses the same governance Python package to compose Team A/C into a temporary catalog, generate the native composite CDO SQL/YAML, validate, build the CDO view in Neon and commit the compiled output to `generated/production`. dbt Cloud deployment remains separate.

## Commands

Install from a checkout of this repository:

```bash
python -m pip install -e ./cdo/validator
python -m pytest cdo/validator/tests -q
```

From a **disposable federated dbt working copy**, with the paths adjusted as needed:

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
  --output /tmp/current_cdo_catalog.yml
```

Generate the native dbt CDO SQL/YAML from the temporary catalog:

```bash
python -m meta_context_validator.generate_cdo_dbt \
  --catalog /tmp/current_cdo_catalog.yml \
  --out models/semantic_models/team_cdo/generated
```

The governance repository does not store a generated composition catalog. The federated consolidated promotion workflow owns native CDO output in `generated/production`.

The compiler writes expanded YAML into the working copy: do **not** commit those files over Team A/C's source declarations. Use the federated publishing workflow to create deployment-ready YAML.

## What fails a PR?

Examples: unsupported CDO parent/version, duplicate inherited columns, invalid metric aliases, missing declared required columns, mismatched declared column types, native model contract enforcement disabled, missing enterprise context metadata, or a physical SQL type mismatch during the live build.

See [`cdo/README.md`](cdo/README.md) for a focused contract reference and [`cdo/validator/README.md`](cdo/validator/README.md) for the Python CLI.

## Design boundaries

- The registry format is **custom**, compiled into native dbt syntax; it is not an Apache OSI or native dbt semantic-model specification.
- Independent model names are supported; CDO does not prescribe a team's staging model name.
- Contract validation discovers opted-in implementations using `config.meta.semantic_contract.implements` in `manifest.json`. The CLI fails closed when no CDO implementation exists in the manifest it was asked to validate.
- The optional Meta:Context CLI is retained as a separate utility, but it is not part of the active federated CDO validation or release path.
- Legacy upstream research documents, authoring skill, example, and the obsolete metric-only generator have been removed from this POC repository. The active Meta:Context validator code and regression tests remain.

## Links

- [Federated dbt POC](https://github.com/robin-bajaj/federated-semantic-poc)
- [CDO Position registry](cdo/definitions/position_v1.yml)
- [Contract compiler](cdo/validator/meta_context_validator/semantic_compiler.py)
- [Manifest contract validator](cdo/validator/meta_context_validator/contract_rules.py)
