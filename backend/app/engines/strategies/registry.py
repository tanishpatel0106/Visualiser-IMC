"""Strategy registry for the built-in strategy library.

Provides a central catalog of available strategies with metadata,
so the frontend can display them and the sandbox can instantiate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategyDefinition:
    """Metadata and source code for a single built-in strategy."""

    strategy_id: str
    name: str
    category: str
    description: str
    source_code: str
    parameters: dict[str, dict] = field(default_factory=dict)


class StrategyRegistry:
    """Central registry of built-in strategy definitions.

    Usage
    -----
    >>> registry = StrategyRegistry()
    >>> registry.load_builtins()
    >>> all_strats = registry.get_all()
    >>> mm_strats = registry.get_by_category("market_making")
    """

    def __init__(self) -> None:
        self._strategies: dict[str, StrategyDefinition] = {}

    def register(self, strategy_def: StrategyDefinition) -> None:
        """Register a strategy definition."""
        self._strategies[strategy_def.strategy_id] = strategy_def

    def get_all(self) -> list[StrategyDefinition]:
        """Return all registered strategy definitions."""
        return list(self._strategies.values())

    def get_by_id(self, strategy_id: str) -> Optional[StrategyDefinition]:
        """Return a single strategy by its ID, or None."""
        return self._strategies.get(strategy_id)

    def get_by_category(self, category: str) -> list[StrategyDefinition]:
        """Return all strategies belonging to a category."""
        return [s for s in self._strategies.values() if s.category == category]

    def load_builtins(self) -> None:
        """Load all built-in strategies from the library modules."""
        from backend.app.engines.strategies import (
            market_making,
            mean_reversion,
            microstructure,
            momentum,
        )

        modules = [market_making, mean_reversion, momentum, microstructure]
        for module in modules:
            if hasattr(module, "STRATEGY_DEFINITIONS"):
                for sdef in module.STRATEGY_DEFINITIONS:
                    self.register(sdef)
