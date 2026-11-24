"""Deprecated compatibility shim for :mod:`cdo_governance.semantic.semantic_compiler`.

Use the descriptive module name for new imports and CLI invocations.
"""
from .semantic_compiler import *  # noqa: F401,F403 - legacy public imports
from . import semantic_compiler as _implementation


def __getattr__(name):
    return getattr(_implementation, name)


if __name__ == "__main__":
    _implementation.main()
