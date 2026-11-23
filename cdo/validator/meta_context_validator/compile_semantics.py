"""CLI entrypoint for CDO Position inheritance compilation."""
import argparse
from pathlib import Path
from .semantic.inheritance import compile_semantics

def main():
    parser = argparse.ArgumentParser(description="Compile CDO inheritance to native dbt YAML")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    files = compile_semantics(args.project, args.registry)
    for file in files:
        print(f"Compiled inherited semantic model: {file}")
    print(f"CDO semantic inheritance compiled: {len(files)} files")

if __name__ == "__main__":
    main()
