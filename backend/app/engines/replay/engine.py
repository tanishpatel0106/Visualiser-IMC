"""Replay engine for stepping through a recorded event stream.

Supports forward/backward stepping, seeking by timestamp, speed control,
and convenience jumps (next trade, next fill).  Works as a standalone
passive replay or with a ``ReplayState`` attached for full state tracking.
"""

import bisect
import uuid
from typing import Optional

from app.models.events import Event, EventType


class ReplayEngine:
    """Core replay controller that manages a linear event timeline.

    The engine itself is deliberately *stateless* with respect to market
    data -- it only tracks the event list and playback cursor.  Pair it
    with :class:`ReplayState` for order-book / position reconstruction.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._current_index: int = -1
        self._is_playing: bool = False
        self._speed: float = 1.0
        self._session_id: str = str(uuid.uuid4())

        # Lightweight frame cache: maps index -> Event for visited indices.
        # Enables efficient step_backward without re-scanning.
        self._frame_cache: dict[int, Event] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[Event]:
        return self._events

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def session_id(self) -> str:
        return self._session_id

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_events(self, events: list[Event]) -> None:
        """Set (or replace) the event stream and reset the cursor."""
        self._events = sorted(events, key=lambda e: (e.timestamp, e.sequence_num))
        self._current_index = -1
        self._is_playing = False
        self._frame_cache.clear()
        self._session_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    def play(self) -> None:
        """Begin (or resume) playback."""
        if not self._events:
            return
        self._is_playing = True

    def pause(self) -> None:
        """Pause playback at the current position."""
        self._is_playing = False

    def stop(self) -> None:
        """Stop playback and reset to the beginning."""
        self._is_playing = False
        self._current_index = -1

    def set_speed(self, speed: float) -> None:
        """Set the playback speed multiplier (e.g. 2.0 = double speed)."""
        if speed > 0:
            self._speed = speed

    # ------------------------------------------------------------------
    # Stepping
    # ------------------------------------------------------------------

    def step_forward(self) -> Optional[Event]:
        """Advance the cursor by one event and return it.

        Returns ``None`` if already at the end of the stream.
        """
        if not self._events:
            return None
        next_idx = self._current_index + 1
        if next_idx >= len(self._events):
            self._is_playing = False
            return None
        self._current_index = next_idx
        event = self._events[next_idx]
        self._frame_cache[next_idx] = event
        return event

    def step_backward(self) -> Optional[Event]:
        """Move the cursor back by one event and return it.

        Returns ``None`` if already at (or before) the start.
        """
        if self._current_index <= 0:
            return None
        self._current_index -= 1
        # Prefer the cache -- it will always be populated for visited indices.
        return self._frame_cache.get(
            self._current_index, self._events[self._current_index]
        )

    # ------------------------------------------------------------------
    # Seeking
    # ------------------------------------------------------------------

    def seek(self, timestamp: int) -> Optional[Event]:
        """Binary-search to the event nearest to *timestamp*.

        Finds the rightmost event whose timestamp is <= *timestamp*.
        Returns ``None`` if the stream is empty.
        """
        if not self._events:
            return None

        timestamps = [e.timestamp for e in self._events]
        idx = bisect.bisect_right(timestamps, timestamp) - 1
        if idx < 0:
            idx = 0
        self._current_index = idx
        event = self._events[idx]
        self._frame_cache[idx] = event
        return event

    # ------------------------------------------------------------------
    # Convenience jumps
    # ------------------------------------------------------------------

    def jump_to_next_trade(self) -> Optional[Event]:
        """Skip forward to the next ``TRADE_PRINT`` event."""
        return self._jump_to_next_type(EventType.TRADE_PRINT)

    def jump_to_next_fill(self) -> Optional[Event]:
        """Skip forward to the next ``FILL`` event."""
        return self._jump_to_next_type(EventType.FILL)

    def _jump_to_next_type(self, event_type: EventType) -> Optional[Event]:
        """Advance cursor to the next event of the given type."""
        start = self._current_index + 1
        for i in range(start, len(self._events)):
            if self._events[i].event_type == event_type:
                self._current_index = i
                event = self._events[i]
                self._frame_cache[i] = event
                return event
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_current_event(self) -> Optional[Event]:
        """Return the event at the current cursor position."""
        if 0 <= self._current_index < len(self._events):
            return self._events[self._current_index]
        return None

    def get_current_timestamp(self) -> int:
        """Return the timestamp of the current event, or 0."""
        event = self.get_current_event()
        return event.timestamp if event else 0

    def get_progress(self) -> float:
        """Return playback progress as a float in [0.0, 1.0]."""
        if not self._events:
            return 0.0
        if self._current_index < 0:
            return 0.0
        return (self._current_index + 1) / len(self._events)

    def get_events_up_to_current(self) -> list[Event]:
        """Return all events from the start up to and including the current index."""
        if self._current_index < 0 or not self._events:
            return []
        return self._events[: self._current_index + 1]

    def get_session_state(self) -> dict:
        """Return a dict summarising the full engine state."""
        return {
            "session_id": self._session_id,
            "total_events": len(self._events),
            "current_index": self._current_index,
            "is_playing": self._is_playing,
            "speed": self._speed,
            "progress": self.get_progress(),
            "current_timestamp": self.get_current_timestamp(),
            "current_event_type": (
                self.get_current_event().event_type.value
                if self.get_current_event()
                else None
            ),
        }
