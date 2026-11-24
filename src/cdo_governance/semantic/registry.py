"""Deprecated compatibility shim for :mod:`cdo_governance.semantic.contract_registry`.

Use the descriptive module name for new imports and CLI invocations.
"""
from .contract_registry import *  # noqa: F401,F403 - legacy public imports
from . import contract_registry as _implementation


def __getattr__(name):
    return getattr(_implementation, name)


if __name__ == "__main__":
    _implementation.main()
