"""Factory for selecting the DB minimizer implementation.

Config: `config.minimizer` in [view, copy, pk, hybrid]. Default: view.
"""
from .copy_based_minimizer import CopyBasedMinimizer
from .hybrid_minimizer import HybridMinimizer
from .pk_view_minimizer import PKViewMinimizer
from .view_minimizer import ViewMinimizer

_ALIASES = {
    "view": "view",
    "view_minimizer": "view",
    "copy": "copy",
    "copy_based": "copy",
    "copybased": "copy",
    "pk": "pk",
    "pk_view": "pk",
    "pkview": "pk",
    "hybrid": "hybrid",
}


def get_minimizer_class(name=None, config=None):
    key = (name or (getattr(config, "minimizer", "view") if config is not None else "view") or "view")
    key = str(key).lower().strip()
    key = _ALIASES.get(key, "view")
    return {
        "view": ViewMinimizer,
        "copy": CopyBasedMinimizer,
        "pk": PKViewMinimizer,
        "hybrid": HybridMinimizer,
    }[key]


def create_minimizer(connectionHelper, core_relations, all_sizes, sampling_status, expect_populated=True, name=None):
    cls = get_minimizer_class(name=name, config=getattr(connectionHelper, "config", None))
    return cls(connectionHelper, core_relations, all_sizes, sampling_status,
               expect_populated=expect_populated)
