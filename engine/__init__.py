"""C2 collaborative authoring engine (V0-V3).

This package implements the bounded, local, single-author collaborative
problem-setting slice described in
``docs/research/agentic-engine-portfolio`` (revision C2, documents 03-08).

It is additive to the existing author workbench.  The legacy ``agent.py`` /
``graph_agent.py`` chat path is preserved unchanged; this package owns the new
qualified profile, its application ledger, controller and diagnostics.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.3.0"
