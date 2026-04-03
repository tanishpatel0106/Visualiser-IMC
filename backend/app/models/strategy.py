"""Strategy definition and debug frame models."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class StrategyParameter(BaseModel):
    """A single tunable parameter for a strategy."""

    name: str
    param_type: str = "float"
    default: Any = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    options: Optional[list] = None
    description: str = ""

    model_config = {"frozen": False}


class StrategyDefinition(BaseModel):
    """Full definition of a trading strategy."""

    strategy_id: str
    name: str
    category: str = "custom"
    description: str = ""
    source_code: str = ""
    is_builtin: bool = False
    parameters: list[StrategyParameter] = Field(default_factory=list)
    created_at: str = ""

    model_config = {"frozen": False}


class DebugFrame(BaseModel):
    """
    A single debug snapshot capturing full strategy state at one timestamp.
    Used for step-through debugging and post-hoc analysis.
    """

    timestamp: int = 0
    product: str = ""
    market_state: dict = Field(default_factory=dict)
    strategy_inputs: dict = Field(default_factory=dict)
    strategy_outputs: dict = Field(default_factory=dict)
    orders_submitted: list = Field(default_factory=list)
    fills: list = Field(default_factory=list)
    position: dict = Field(default_factory=dict)
    pnl: dict = Field(default_factory=dict)
    warnings: list = Field(default_factory=list)
    notes: list = Field(default_factory=list)

    model_config = {"frozen": False}
