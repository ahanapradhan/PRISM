"""Backward-compatible shim. Canonical implementation: pk_view_minimizer.py."""
from .pk_view_minimizer import PKViewMinimizer, PKView_Minimizer  # noqa: F401

__all__ = ["PKViewMinimizer", "PKView_Minimizer"]
