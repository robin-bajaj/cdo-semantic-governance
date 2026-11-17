# Shared CDO P&L definition (custom pre-parse extension)

The canonical CDO business specification is
`cdo/definitions/position_v1.yml`; it includes **both** common Position
attributes and the approved Profit & Loss metric aggregation.

Team projects define their source columns in staging SQL and include a
reference **inside the model's `metrics:` list**, not `metric_bindings`
under model-level metadata:

```yaml
models:
  - name: stg_team_a_positions
    config:
      meta:
        semantic_contract:
          implements: cdo.position
          version: 1
    semantic_model:
      enabled: true
      name: team_a_equity_positions
    columns:
      - name: profit_loss
        data_type: numeric
    metrics:
      - name: equity_profit_loss
        label: Equity Profit and Loss
        config:
          meta:
            metric_contract:
              implements: cdo.profit_loss
              version: 1
```

Run the generator in a disposable checked-out dbt project **before**
`dbt parse`:

```bash
python -m meta_context_validator.generate_metrics \
  --registry /path/to/cdo-semantic-contract-validator/cdo/definitions/position_v1.yml \
  --project /path/to/team-dbt-project
```

The generated native metric contains `type: simple`, `agg: sum`,
`expr: profit_loss`, and `fill_nulls_with: 0`. The generator is
idempotent; unknown references and conflicting calculations fail the build.
The generator edits the working copy; its output is **not committed by our
current GitHub Actions workflow**. Native dbt Studio parsing of reference-only
YAML still requires a local generation step or a separate generated-artifact
publishing process. Central metric governance does not certify the underlying
position-level P&L computations in each team's source.
