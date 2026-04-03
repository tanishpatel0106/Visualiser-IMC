"""High-level replay service that bridges the API layer to the replay engine."""

import logging
from typing import Optional

from backend.app.engines.replay.engine import ReplayEngine
from backend.app.engines.replay.state import ReplayState
from backend.app.services.dataset_service import DatasetService

logger = logging.getLogger(__name__)


class ReplayService:
    """Orchestrates interactive market replay sessions.

    Wraps :class:`ReplayEngine` and :class:`ReplayState` to provide
    a convenient interface for the API layer.
    """

    def __init__(
        self,
        replay_engine: ReplayEngine,
        dataset_service: DatasetService,
    ) -> None:
        self._engine = replay_engine
        self._dataset = dataset_service
        self._state = ReplayState()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_replay(
        self,
        products: list[str],
        days: list[int],
        strategy_id: Optional[str] = None,
    ) -> dict:
        """Load events for the given products/days and initialise the replay."""
        events = self._dataset.get_event_stream(products, days)
        if not events:
            return {"error": "No events found for the given products and days"}

        self._engine.load_events(events)
        self._state.reset()

        return {
            "session_id": self._engine.session_id,
            "total_events": len(events),
            "products": products,
            "days": days,
            "strategy_id": strategy_id,
        }

    def pause_replay(self) -> dict:
        """Pause the running replay."""
        self._engine.pause()
        return self._engine.get_session_state()

    def step_forward(self) -> dict:
        """Step one event forward and return event + state snapshot."""
        event = self._engine.step_forward()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        changes = self._state.process_event(event)
        return {
            "done": False,
            "event": event.model_dump(),
            "changes": changes,
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    def step_backward(self) -> dict:
        """Step one event backward.

        Note: backward stepping returns the event at the new position
        but does NOT reverse state changes. A full state reconstruction
        would require replaying from the beginning up to the new cursor.
        """
        event = self._engine.step_backward()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        return {
            "done": False,
            "event": event.model_dump(),
            **self._engine.get_session_state(),
        }

    def seek(self, timestamp: int) -> dict:
        """Seek to the nearest event at the given timestamp.

        Rebuilds state by replaying all events from the beginning up to
        the new cursor position.
        """
        event = self._engine.seek(timestamp)
        if event is None:
            return {"error": "Empty event stream"}

        # Rebuild state up to current position
        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    def set_speed(self, speed: float) -> None:
        """Set the playback speed multiplier."""
        self._engine.set_speed(speed)

    def get_state(self) -> dict:
        """Return the current engine + world state."""
        return {
            "engine": self._engine.get_session_state(),
            "state": self._state.get_state_snapshot(),
        }

    def reset(self) -> None:
        """Full reset of engine and state."""
        self._engine.stop()
        self._state.reset()

    # ------------------------------------------------------------------
    # Convenience jumps
    # ------------------------------------------------------------------

    def jump_next_trade(self) -> dict:
        """Jump to the next TRADE_PRINT event."""
        event = self._engine.jump_to_next_trade()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        # Replay state up to new position
        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "done": False,
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    def jump_next_fill(self) -> dict:
        """Jump to the next FILL event."""
        event = self._engine.jump_to_next_fill()
        if event is None:
            return {"done": True, **self._engine.get_session_state()}

        self._state.reset()
        for ev in self._engine.get_events_up_to_current():
            self._state.process_event(ev)

        return {
            "done": False,
            "event": event.model_dump(),
            "state": self._state.get_state_snapshot(),
            **self._engine.get_session_state(),
        }

    # ------------------------------------------------------------------
    # Accessors for WebSocket streaming
    # ------------------------------------------------------------------

    @property
    def engine(self) -> ReplayEngine:
        return self._engine

    @property
    def state(self) -> ReplayState:
        return self._state
