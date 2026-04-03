"""Event system models for the IMC Prosperity trading terminal."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events flowing through the system."""

    BOOK_SNAPSHOT = "BOOK_SNAPSHOT"
    TRADE_PRINT = "TRADE_PRINT"
    STRATEGY_SUBMIT = "STRATEGY_SUBMIT"
    STRATEGY_CANCEL = "STRATEGY_CANCEL"
    FILL = "FILL"
    REJECT = "REJECT"
    TIMER_TICK = "TIMER_TICK"
    REPLAY_START = "REPLAY_START"
    REPLAY_PAUSE = "REPLAY_PAUSE"
    REPLAY_STEP = "REPLAY_STEP"
    REPLAY_SEEK = "REPLAY_SEEK"
    RUN_COMPLETE = "RUN_COMPLETE"


class Event(BaseModel):
    """
    A single event in the event stream.

    Events are the universal message type flowing between replay engine,
    matching engine, strategy runner, and the frontend via WebSocket.
    """

    event_type: EventType
    timestamp: int
    product: Optional[str] = None
    data: dict = Field(default_factory=dict)
    sequence_num: int = 0

    model_config = {"frozen": False}
