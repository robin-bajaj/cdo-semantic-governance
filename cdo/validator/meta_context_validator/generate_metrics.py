"""Command line entry point for the custom, CDO-governed metric generator."""

import argparse
from pathlib import Path

from .metric_generator import generate_metrics


def main():
    parser = argparse.ArgumentParser(description="Generate dbt metrics from unified CDO semantic definitions")
    parser.add_argument("--registry", type=Path, required=True, help="CDO semantic definition YAML file or directory")
    parser.add_argument("--project", type=Path, required=True, help="dbt project root")
    args = parser.parse_args()
    updated = generate_metrics(args.project, args.registry)
    for path in updated:
        print(f"Generated governed metrics: {path}")
    print(f"CDO metric generation complete ({len(updated)} files updated)")


if __name__ == "__main__":
    main()
