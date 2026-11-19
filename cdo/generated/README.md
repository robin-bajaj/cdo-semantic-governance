# Generated enterprise semantic catalog

This directory is for **CDO composition outputs**, not authored CDO standards.

- Authoritative contracts: `cdo/definitions/position_v1.yml`
- Compiler: `cdo/validator/meta_context_validator/semantic_compiler.py`
- Post-validation composer: `cdo/validator/meta_context_validator/compose_cdo.py`
- Example publish destination: `generated/cdo/position/v1/cdo_enterprise_positions.yml`

The generated catalog is intentionally **custom metadata** and is **not** a dbt
`semantic_model` or a routed SQL endpoint. It preserves every compiled column,
entity/dimension property, local metric, inherited metric, ownership, and
canonical-to-team entity alias per validated implementation. The included CDO
enterprise derived metrics retain references to their participating team metrics.

Generate from a **disposable, compiled dbt project checkout** only:

```bash
python -m meta_context_validator.compile_semantics \
  --registry ../contract-validator/cdo/definitions/position_v1.yml \
  --project .

dbt parse --no-partial-parse

python -m meta_context_validator.compose_cdo \
  --project . \
  --contract ../contract-validator/cdo/definitions/position_v1.yml \
  --manifest target/manifest.json \
  --enterprise-metrics models/semantic_models/team_cdo/enterprise_metrics.yml \
  --require-semantic-model team_a_equity_positions \
  --require-semantic-model team_c_fi_positions \
  --output generated/cdo/position/v1/cdo_enterprise_positions.yml
```

The command verifies the CDO manifest contract, inherited entity semantics and
metric formulas, preserves team extensions, and rejects missing team models,
name collisions and unresolved enterprise metric dependencies. It does **not**
run `dbt build`, certify P&L accuracy, or make the catalog automatically
queryable through Power BI.

Do not commit compiled team YAML over its source declaration. Keep generated
catalogs in a separate directory or publish branch after the CI gate passes.
