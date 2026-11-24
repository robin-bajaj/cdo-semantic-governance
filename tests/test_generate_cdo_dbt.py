"""Regression tests for the governance-owned native CDO dbt generator."""
import yaml
from cdo_governance.semantic.dbt_generator import generate


def test_generate_native_cdo_from_two_team_catalog(tmp_path):
    catalog = {
        "catalog_format": "cdo-federated-semantic-catalog/v1",
        "contract": {"name": "cdo.position", "version": 1},
        "common_attributes": ["position_id", "report_date", "profit_loss", "instrument_code"],
        "metric_definitions": [
            {"name": "total_profit_loss", "description": "Total position P&L",
             "type": "simple", "agg": "sum", "expr": "profit_loss", "fill_nulls_with": 0},
        ],
        "attribute_definitions": [
            {"name": "position_id", "data_type": "text", "description": "Position identifier"},
            {"name": "report_date", "data_type": "date", "description": "Reporting date"},
            {"name": "profit_loss", "data_type": "numeric", "description": "Profit or loss"},
            {"name": "instrument_code", "data_type": "integer", "description": "Instrument"},
        ],
        "implementations": [
            {
                "semantic_model": "team_a_equity_positions",
                "source_model": "stg_team_a_positions",
                "owner": "lob_team_a",
                "included_attributes": ["position_id", "report_date", "profit_loss", "instrument_code"],
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
                "included_attributes": ["position_id", "report_date", "profit_loss", "instrument_code"],
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
    metrics = {metric["name"]: metric for metric in native["metrics"]}
    assert {"cdo_total_profit_loss", "cdo_equity_total_mtm", "cdo_fi_total_settled_cash"} <= set(metrics)
    assert metrics["cdo_total_profit_loss"]["fill_nulls_with"] == 0
    assert metrics["cdo_total_profit_loss"]["expr"] == "profit_loss"


def test_sql_null_pads_optional_business_attribute(tmp_path):
    catalog = {
        "catalog_format": "cdo-federated-semantic-catalog/v1",
        "contract": {"name": "cdo.position", "version": 1},
        "common_attributes": ["position_id", "report_date", "profit_loss", "instrument_code"],
        "metric_definitions": [
            {"name": "total_profit_loss", "description": "Total position P&L",
             "type": "simple", "agg": "sum", "expr": "profit_loss", "fill_nulls_with": 0},
        ],
        "attribute_definitions": [
            {"name": "position_id", "data_type": "text", "description": "ID"},
            {"name": "report_date", "data_type": "date", "description": "Date"},
            {"name": "profit_loss", "data_type": "numeric", "description": "P&L"},
            {"name": "instrument_code", "data_type": "integer", "description": "Instrument"},
        ],
        "implementations": [
            {"semantic_model": "team_a_equity_positions", "source_model": "stg_team_a_positions",
             "owner": "A", "included_attributes": ["position_id", "report_date", "profit_loss", "instrument_code"],
             "columns": [{"name": k, "data_type": v} for k, v in
                         [("position_id", "text"), ("report_date", "date"), ("profit_loss", "numeric"), ("instrument_code", "integer")]],
             "metrics": []},
            {"semantic_model": "team_c_fi_positions", "source_model": "stg_team_c_positions",
             "owner": "C", "included_attributes": ["position_id", "report_date", "profit_loss"],
             "columns": [{"name": k, "data_type": v} for k, v in
                         [("position_id", "text"), ("report_date", "date"), ("profit_loss", "numeric")]],
             "metrics": []},
        ],
    }
    path = tmp_path / "catalog.yml"
    path.write_text(yaml.safe_dump(catalog))
    out = tmp_path / "native"
    generate(path, out)
    sql = (out / "cdo_enterprise_positions.sql").read_text()
    assert "null::integer as instrument_code" in sql
    native = yaml.safe_load((out / "cdo_enterprise_positions.yml").read_text())
    assert next(c for c in native["models"][0]["columns"] if c["name"] == "instrument_code")["data_type"] == "integer"


def test_fails_closed_if_governed_profit_formula_missing(tmp_path):
    import pytest
    # This deliberately minimal catalog verifies the generator validates its
    # authoritative metric dependency before writing any output.
    catalog = {
        "catalog_format": "cdo-federated-semantic-catalog/v1",
        "contract": {"name": "cdo.position", "version": 1},
        "common_attributes": ["position_id", "report_date", "profit_loss"],
        "attribute_definitions": [
            {"name": "position_id", "data_type": "text"},
            {"name": "report_date", "data_type": "date"},
            {"name": "profit_loss", "data_type": "numeric"},
        ],
        "implementations": [
            {"semantic_model": "team_a_equity_positions", "source_model": "stg_team_a_positions",
             "included_attributes": ["position_id", "report_date", "profit_loss"],
             "columns": [{"name": "position_id", "data_type": "text"},
                         {"name": "report_date", "data_type": "date"},
                         {"name": "profit_loss", "data_type": "numeric"}],
             "metrics": []},
            {"semantic_model": "team_c_fi_positions", "source_model": "stg_team_c_positions",
             "included_attributes": ["position_id", "report_date", "profit_loss"],
             "columns": [{"name": "position_id", "data_type": "text"},
                         {"name": "report_date", "data_type": "date"},
                         {"name": "profit_loss", "data_type": "numeric"}],
             "metrics": []},
        ],
    }
    source = tmp_path / "catalog.yml"
    source.write_text(yaml.safe_dump(catalog))
    with pytest.raises(ValueError, match="governed Position P&L metric"):
        generate(source, tmp_path / "generated")
    assert not (tmp_path / "generated" / "cdo_enterprise_positions.yml").exists()
