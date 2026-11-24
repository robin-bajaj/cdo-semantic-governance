"""Deprecated compatibility shim for :mod:`cdo_governance.validation.contract_validator`.

Use the descriptive module name for new imports and CLI invocations.
"""
from .contract_validator import *  # noqa: F401,F403 - legacy public imports
from . import contract_validator as _implementation


def __getattr__(name):
    return getattr(_implementation, name)


