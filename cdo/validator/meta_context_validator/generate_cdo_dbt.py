"""Compatibility CLI/API for native CDO dbt SQL and YAML generation.

Canonical module: meta_context_validator.semantic.dbt_generator
"""
from .semantic.dbt_generator import *  # noqa: F401,F403
from .semantic.dbt_generator import main

if __name__ == "__main__":
    main()
