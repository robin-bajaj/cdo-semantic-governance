"""Regression tests for the governance-owned native CDO dbt generator."""
import yaml
from meta_context_validator.generate_cdo_dbt import generate


def test_generate_native_cdo_from_two_team_catalog(tmp_path):
    catalog = {
        "catalog_format": "cdo-federated-semantic-catalog/v1",
        "contract": {"name": "cdo.position", "version": 1},
        "common_attributes": ["position_id", "report_date", "profit_loss", "instrument_code"],
        "implementations": [
            {
                "semantic_model": "team_a_equity_positions",
                "source_model": "stg_team_a_positions",
                "owner": "lob_team_a",
                "columns": [
                    {"name": "position_id", "data_type": "text"},
                    {"name": "report_date", "data_type": "date"},
                    {"name": "profit_loss", "data_type": "numeric"},
                    {"name": "instrument_code", "data_type": "integer"},
                    {"name": "mtm", "data_type": "numeric"},
                ],
                "metrics": [
                    {"name": "equity_profit_loss", "type": "simple", "agg": "sum", "expr": "profit_loss"},
                    {"name": "equity_total_mtm", "label": "Equity Total MTM", "type": "simple", "agg": "sum", "expr": "mtm"},
                ],
            },
            {
                "semantic_model": "team_c_fi_positions",
                "source_model": "stg_team_c_positions",
                "owner": "lob_team_c",
                "columns": [
                    {"name": "position_id", "data_type": "text"},
                    {"name": "report_date", "data_type": "date"},
                    {"name": "profit_loss", "data_type": "numeric"},
                    {"name": "instrument_code", "data_type": "integer"},
                    {"name": "settled_cash", "data_type": "numeric"},
                ],
                "metrics": [
                    {"name": "fixed_income_profit_loss", "type": "simple", "agg": "sum", "expr": "profit_loss"},
                    {"name": "fi_total_settled_cash", "label": "FI Total Settled Cash", "type": "simple", "agg": "sum", "expr": "settled_cash"},
                ],
            },
        ],
    }
    input_path = tmp_path / "catalog.yml"
    input_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    output_dir = tmp_path / "generated"

    result = generate(input_path, output_dir)
    sql = (output_dir / "cdo_enterprise_positions.sql").read_text()
    native = yaml.safe_load(result.read_text())["models"][0]

    assert "ref('stg_team_a_positions')" in sql
    assert "ref('stg_team_c_positions')" in sql
    assert "union all" in sql
    assert "null::numeric as settled_cash" in sql
    assert "null::numeric as mtm" in sql
    assert native["semantic_model"]["enabled"] is True
    assert native["primary_entity"] == "cdo_position"
    metrics = {metric["name"] for metric in native["metrics"]}
    assert {"cdo_total_profit_loss", "cdo_equity_total_mtm", "cdo_fi_total_settled_cash"} <= metrics
