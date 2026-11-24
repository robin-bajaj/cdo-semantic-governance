"""Validate dbt models against CDO-owned, reusable semantic contracts.

Independent dbt projects may use different model names. In the preferred mode,
the contract contains semantic_columns but no required_models; the validator
discovers implementations via config.meta.semantic_contract.implements.
Legacy required_models contracts are still supported for compatibility.
"""

import re


def normalize_type(value):
    """Normalize formatting for strict declared-type comparison."""
    return re.sub(r"\s+", "", str(value or "").lower())


def _implementation(node: dict) -> dict:
    """Return declared contract metadata from a dbt manifest model node."""
    config = node.get("config") or {}
    meta = config.get("meta") or node.get("meta") or {}
    return meta.get("semantic_contract") or {}


def validate_cdo_contract(manifest: dict, contract: dict) -> list[str]:
    """Return contract violations (an empty list means validation passed).

    Preferred independent-project mode:
        Contract specifies name/version/semantic_columns, not required_models.
        Validate all models in this manifest declaring implements == name.
        Fail when none declares it, so deleting declarations cannot silently pass.

    Legacy single-project mode:
        If required_models is explicitly present, validate those named models.
    """
    name = contract["name"]
    version = str(contract["version"])
    # The semantic definition is also the required data interface.
    # Reject the legacy duplicated mapping to prevent conflicting sources of truth.
    if "required_columns" in contract:
        raise ValueError("CDO contract must define columns only in semantic_columns")
    semantic_columns = contract.get("attributes", contract.get("semantic_columns"))
    if not isinstance(semantic_columns, list) or not semantic_columns:
        raise ValueError("CDO contract requires a non-empty attributes list")
    columns_required = {}
    for column in semantic_columns:
        if not isinstance(column, dict):
            raise ValueError("CDO semantic_columns must contain mappings")
        column_name, data_type = column.get("name"), column.get("data_type")
        if not isinstance(column_name, str) or not column_name.strip():
            raise ValueError("CDO semantic column must have a non-empty name")
        if not isinstance(data_type, str) or not data_type.strip():
            raise ValueError(f"CDO semantic column {column_name} must have a data_type")
        if column_name in columns_required:
            raise ValueError(f"Duplicate CDO semantic column {column_name}")
        columns_required[column_name] = data_type

    nodes = manifest.get("nodes") or {}
    models = [
        node for node in nodes.values()
        if node.get("resource_type") == "model"
    ]
    errors = []

    if "required_models" in contract:
        # Backward compatibility for POCs which listed all models centrally.
        required_models = contract["required_models"]
        if not isinstance(required_models, list) or not required_models:
            raise ValueError("required_models must be a non-empty list")
        selected = []
        for model_name in required_models:
            matches = [m for m in models if m.get("name") == model_name]
            if not matches:
                errors.append(f"{model_name}: Model not found")
            elif len(matches) > 1:
                errors.append(f"{model_name}: Multiple models found with this name")
            else:
                selected.append(matches[0])
    else:
        # No globally prescribed physical model names; each team owns its own.
        selected = [m for m in models if _implementation(m).get("implements") == name]
        if not selected:
            return [
                f"No models in this dbt manifest declare "
                f"config.meta.semantic_contract.implements: {name}"
            ]

    for model in selected:
        model_name = model.get("name") or "<unnamed model>"
        implementation = _implementation(model)

        if implementation.get("implements") != name:
            errors.append(f"{model_name}: Does not implement {name}")

        if str(implementation.get("version")) != version:
            errors.append(
                f"{model_name}: Contract version mismatch. "
                f"Expected {version}, got {implementation.get('version')}"
            )

        # Compiled implementations record their explicit CDO attribute whitelist.
        # Legacy manifests without a marker remain checked against all fields.
        selected_names = implementation.get("included_attributes")
        if selected_names is None:
            selected_names = list(columns_required)
        if (not isinstance(selected_names, list) or not selected_names
                or len(selected_names) != len(set(selected_names))
                or any(name not in columns_required for name in selected_names)):
            errors.append(f"{model_name}: invalid included_attributes whitelist")
            continue

        columns = model.get("columns") or {}
        for column_name in selected_names:
            expected_type = columns_required[column_name]
            column = columns.get(column_name)
            if column is None:
                errors.append(
                    f"{model_name}: Missing mandatory column {column_name}"
                )
                continue

            actual_type = column.get("data_type")
            if normalize_type(actual_type) != normalize_type(expected_type):
                errors.append(
                    f"{model_name}: Incorrect type for {column_name}. "
                    f"Expected {expected_type}, got {actual_type}"
                )

        if contract.get("require_native_contract", "attributes" in contract):
            config = model.get("config") or {}
            native_contract = config.get("contract") or {}
            if not native_contract.get("enforced", False):
                errors.append(
                    f"{model_name}: Native dbt contract is not enforced"
                )

    return errors
