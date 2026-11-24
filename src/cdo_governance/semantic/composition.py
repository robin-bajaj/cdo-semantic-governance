"""Deprecated compatibility shim for :mod:`cdo_governance.semantic.position_composer`.

Use the descriptive module name for new imports and CLI invocations.
"""
from .position_composer import *  # noqa: F401,F403 - legacy public imports
from . import position_composer as _implementation


def __getattr__(name):
    return getattr(_implementation, name)


if __name__ == "__main__":
    _implementation.main()
