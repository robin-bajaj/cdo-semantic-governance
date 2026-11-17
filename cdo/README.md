# CDO governed Position semantic definition

CDO maintains **one canonical custom business definition file**:

`cdo/definitions/position_v1.yml`

Its `semantic_columns` list is the single source for required Position attributes,
types, entities, and dimensions. The registry also defines
the approved `cdo.profit_loss` metric (`SUM(profit_loss)`).
It is **not native dbt semantic_model YAML**: the Python extension translates
metric-level references into native MetricFlow YAML before dbt parses.

```text
cdo/
  definitions/
    position_v1.yml                   # Common Position contract AND metrics
  validator/
    pyproject.toml
    meta_context_validator/
      cli.py                           # dbt-mc validate command
      contract_rules.py                # Required column/type checks
      rules.py                         # Green Dot Meta:Context checks
      metric_generator.py              # Expand metric references
      generate_metrics.py              # Generator command entry point
    tests/
```

Team A / Team C supply independently maintained staging models that declare
`config.meta.semantic_contract.implements: cdo.position`, and place a short
reference under the matching `models[].metrics[]` item:

```yaml
metrics:
  - name: equity_profit_loss
    label: Equity Profit and Loss
    config:
      meta:
        metric_contract:
          implements: cdo.profit_loss
          version: 1
```

For GitHub Actions, check out this repository under `contract-validator/`;
install `./contract-validator/cdo/validator`. Then, while working in
`dbt-project/`:

```bash
python -m meta_context_validator.generate_metrics \
  --registry ../contract-validator/cdo/definitions/position_v1.yml \
  --project .
dbt parse --no-partial-parse
dbt-mc validate models/semantic_models/team_cdo/enterprise_metrics.yml \
  --contracts ../contract-validator/cdo/definitions/position_v1.yml \
  --manifest target/manifest.json
```

**Important:** `config.meta.metric_contract` alone is not valid native metric
inheritance. dbt Studio does not automatically run the generator. Developers
need a generated working tree before parsing in Studio, or a publishing workflow
that makes reviewed, generated dbt YAML available. The registry governs
aggregation of standardized P&L values, **not the calculation of the
position-level values by source systems**.
