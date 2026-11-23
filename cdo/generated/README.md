# Historical generated catalog directory

The governance repository no longer persists its generated composition catalog or runs `generate-cdo-catalog.yml`.

Keep `cdo/definitions/position_v1.yml` as the authoritative contract and use the installed `meta_context_validator.compose_cdo` command to create a **temporary** composition catalog from compiled Team A/C models. Then run `python -m meta_context_validator.generate_cdo_dbt` to create the native dbt CDO SQL/YAML.

The federated `sync-cdo-position-snapshot.yml` workflow owns generation and review of the committed CDO SQL/YAML snapshot. The intermediate catalog is not an executable dbt semantic model and is not persisted here.
