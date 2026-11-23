# CDO Position v1 — governed semantic definition

The [CDO registry](definitions/position_v1.yml) owns the **canonical** enterprise Position interface:

| Attribute | Declared type | Semantic role |
|---|---|---|
| `position_id` | `text` | Primary position entity (team alias supported) |
| `report_date` | `date` | Daily time dimension; aggregation time |
| `profit_loss` | `numeric` | Standardized position P&L |
| `instrument_code` | `integer` | Foreign instrument entity |

The registry also defines the `cdo.profit_loss` metric as `SUM(profit_loss)` and requires `config.contract.enforced: true` for participating dbt models.

**There is no separate `required_columns` list**: each `semantic_columns[]` entry supplies both the mandatory interface and reusable semantics. The registry is a **custom pre-parse DSL**, not native dbt YAML or an OSI schema.

## Implementations

Team A and Team C maintain their own staging SQL and team-specific semantic YAML in the [Federated dbt POC](https://github.com/robin-bajaj/federated-semantic-poc).

A participating model declares `config.meta.semantic_inheritance`, e.g.:

```yaml
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
```

The [compiler](validator/meta_context_validator/semantic/inheritance.py) expands CDO columns, entity/dimension properties and metrics in a temporary checkout, rejecting unsupported versions, duplicate column declarations and alias errors. The compiled YAML gains `config.meta.semantic_contract: {implements: cdo.position, version: 1}` for manifest-based validation. Nonparticipating models (no inheritance declaration) are left unchanged.

## Run the integration

Install the package from this repository:

```bash
python -m pip install -e ./cdo/validator
python -m pytest cdo/validator/tests -q
```

From the **federated dbt project directory** (assuming this repository was checked out at `../contract-validator/`):

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

Next, run `python -m meta_context_validator.generate_cdo_dbt --catalog /tmp/current_cdo_catalog.yml --out models/semantic_models/team_cdo/generated` to produce native dbt SQL/YAML. This output is versioned and reviewed in the federated repository, not stored as a catalog here.

Use a disposable working checkout: compilation rewrites the source YAML in place. The federated PR workflow performs these operations on the Actions runner and builds the staging models with enforced native contracts against PostgreSQL. The combined promotion workflow commits expanded Team A/C and CDO YAML/SQL into `generated/production`; it is **not** a hosted semantic-layer deployment.

See the [repository overview](../README.md) and [CLI documentation](validator/README.md).

## Important limitations

- Manifest validation checks **declared** columns and types, not actual warehouse columns; live dbt build enforces the physical model contract.
- The source systems remain responsible for correctness of position-level `profit_loss` values.
- dbt Studio does not automatically execute the custom semantic compiler when opening reference-only source YAML.
