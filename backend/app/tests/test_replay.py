"""Tests for the ReplayEngine and ReplayState."""

import pytest

from backend.app.engines.replay.engine import ReplayEngine
from backend.app.engines.replay.state import ReplayState
from backend.app.models.events import Event, EventType


# ======================================================================
# Fixtures / helpers
# ======================================================================

@pytest.fixture
def engine():
    return ReplayEngine()


@pytest.fixture
def state():
    return ReplayState()


def _make_events(n=5, start_ts=100, step=100):
    """Create n BOOK_SNAPSHOT events with sequential timestamps."""
    return [
        Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=start_ts + i * step,
            product="X",
            data={
                "day": 1,
                "bid_prices": [99.0],
                "bid_volumes": [10],
                "ask_prices": [101.0],
                "ask_volumes": [15],
                "mid_price": 100.0,
            },
            sequence_num=i + 1,
        )
        for i in range(n)
    ]


def _make_mixed_events():
    """Create a mix of BOOK_SNAPSHOT and TRADE_PRINT events."""
    return [
        Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=100,
            product="X",
            data={
                "day": 1,
                "bid_prices": [99.0],
                "bid_volumes": [10],
                "ask_prices": [101.0],
                "ask_volumes": [15],
                "mid_price": 100.0,
            },
            sequence_num=1,
        ),
        Event(
            event_type=EventType.TRADE_PRINT,
            timestamp=150,
            product="X",
            data={
                "buyer": "Alice",
                "seller": "Bob",
                "symbol": "X",
                "price": 100.0,
                "quantity": 5,
            },
            sequence_num=2,
        ),
        Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=200,
            product="X",
            data={
                "day": 1,
                "bid_prices": [100.0],
                "bid_volumes": [12],
                "ask_prices": [102.0],
                "ask_volumes": [18],
                "mid_price": 101.0,
            },
            sequence_num=3,
        ),
    ]


# ======================================================================
# ReplayEngine.load_events
# ======================================================================

class TestReplayEngineLoadEvents:
    def test_load_events(self, engine):
        events = _make_events(3)
        engine.load_events(events)
        assert len(engine.events) == 3
        assert engine.current_index == -1
        assert engine.is_playing is False

    def test_load_sorts_by_timestamp(self, engine):
        events = [
            Event(event_type=EventType.BOOK_SNAPSHOT, timestamp=300, product="X", sequence_num=3),
            Event(event_type=EventType.BOOK_SNAPSHOT, timestamp=100, product="X", sequence_num=1),
            Event(event_type=EventType.BOOK_SNAPSHOT, timestamp=200, product="X", sequence_num=2),
        ]
        engine.load_events(events)
        assert engine.events[0].timestamp == 100
        assert engine.events[1].timestamp == 200
        assert engine.events[2].timestamp == 300

    def test_load_replaces_previous(self, engine):
        engine.load_events(_make_events(5))
        old_session = engine.session_id
        engine.load_events(_make_events(3))
        assert len(engine.events) == 3
        assert engine.session_id != old_session


# ======================================================================
# ReplayEngine stepping
# ======================================================================

class TestReplayEngineStepping:
    def test_step_forward(self, engine):
        engine.load_events(_make_events(3))

        event = engine.step_forward()
        assert event is not None
        assert event.timestamp == 100
        assert engine.current_index == 0

    def test_step_forward_sequence(self, engine):
        engine.load_events(_make_events(3))

        e1 = engine.step_forward()
        e2 = engine.step_forward()
        e3 = engine.step_forward()
        e4 = engine.step_forward()

        assert e1.timestamp == 100
        assert e2.timestamp == 200
        assert e3.timestamp == 300
        assert e4 is None  # past end

    def test_step_forward_empty_stream(self, engine):
        engine.load_events([])
        assert engine.step_forward() is None

    def test_step_backward(self, engine):
        engine.load_events(_make_events(3))

        engine.step_forward()  # index 0
        engine.step_forward()  # index 1
        event = engine.step_backward()
        assert event is not None
        assert event.timestamp == 100
        assert engine.current_index == 0

    def test_step_backward_at_start(self, engine):
        engine.load_events(_make_events(3))
        engine.step_forward()  # index 0
        assert engine.step_backward() is None  # can't go before 0

    def test_step_backward_before_start(self, engine):
        engine.load_events(_make_events(3))
        assert engine.step_backward() is None  # index is -1


# ======================================================================
# ReplayEngine seeking
# ======================================================================

class TestReplayEngineSeek:
    def test_seek_exact_timestamp(self, engine):
        engine.load_events(_make_events(5))
        event = engine.seek(300)
        assert event is not None
        assert event.timestamp == 300

    def test_seek_between_timestamps(self, engine):
        engine.load_events(_make_events(5))
        # Seek to 250 should find the event at 200 (rightmost <= 250)
        event = engine.seek(250)
        assert event is not None
        assert event.timestamp == 200

    def test_seek_before_all_events(self, engine):
        engine.load_events(_make_events(5, start_ts=100))
        event = engine.seek(50)
        assert event is not None
        # idx would be max(0, bisect_right-1) = 0
        assert event.timestamp == 100

    def test_seek_past_all_events(self, engine):
        engine.load_events(_make_events(3, start_ts=100, step=100))
        event = engine.seek(9999)
        assert event is not None
        assert event.timestamp == 300

    def test_seek_empty_stream(self, engine):
        engine.load_events([])
        assert engine.seek(100) is None


# ======================================================================
# ReplayEngine.get_progress
# ======================================================================

class TestReplayEngineProgress:
    def test_progress_at_start(self, engine):
        engine.load_events(_make_events(5))
        assert engine.get_progress() == 0.0

    def test_progress_after_steps(self, engine):
        engine.load_events(_make_events(5))
        engine.step_forward()  # index 0
        assert engine.get_progress() == pytest.approx(1 / 5)

    def test_progress_at_end(self, engine):
        engine.load_events(_make_events(5))
        for _ in range(5):
            engine.step_forward()
        assert engine.get_progress() == pytest.approx(1.0)

    def test_progress_empty_stream(self, engine):
        engine.load_events([])
        assert engine.get_progress() == 0.0


# ======================================================================
# ReplayEngine playback controls
# ======================================================================

class TestReplayEnginePlayback:
    def test_play_pause(self, engine):
        engine.load_events(_make_events(3))
        engine.play()
        assert engine.is_playing is True
        engine.pause()
        assert engine.is_playing is False

    def test_stop_resets_index(self, engine):
        engine.load_events(_make_events(3))
        engine.step_forward()
        engine.step_forward()
        engine.stop()
        assert engine.current_index == -1
        assert engine.is_playing is False

    def test_set_speed(self, engine):
        engine.set_speed(2.0)
        assert engine.speed == 2.0
        engine.set_speed(0.5)
        assert engine.speed == 0.5
        # Negative speed should be ignored
        engine.set_speed(-1.0)
        assert engine.speed == 0.5  # unchanged


# ======================================================================
# ReplayState.process_event for BOOK_SNAPSHOT
# ======================================================================

class TestReplayStateBookSnapshot:
    def test_process_book_snapshot(self, state):
        event = Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=100,
            product="EMERALDS",
            data={
                "day": 1,
                "bid_prices": [99.0, 98.0],
                "bid_volumes": [10, 20],
                "ask_prices": [101.0, 102.0],
                "ask_volumes": [15, 25],
                "mid_price": 100.0,
            },
        )
        changes = state.process_event(event)

        assert changes["event_type"] == "BOOK_SNAPSHOT"
        assert changes["product"] == "EMERALDS"
        assert "book" in changes
        assert "metrics" in changes

    def test_books_tracked(self, state):
        event = Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=100,
            product="EMERALDS",
            data={
                "day": 1,
                "bid_prices": [99.0],
                "bid_volumes": [10],
                "ask_prices": [101.0],
                "ask_volumes": [15],
                "mid_price": 100.0,
            },
        )
        state.process_event(event)
        books = state.books
        assert "EMERALDS" in books
        assert books["EMERALDS"].best_bid == 99.0


# ======================================================================
# ReplayState.process_event for TRADE_PRINT
# ======================================================================

class TestReplayStateTradePrint:
    def test_process_trade_print(self, state):
        event = Event(
            event_type=EventType.TRADE_PRINT,
            timestamp=100,
            product="EMERALDS",
            data={
                "buyer": "Alice",
                "seller": "Bob",
                "symbol": "EMERALDS",
                "price": 100.0,
                "quantity": 5,
            },
        )
        changes = state.process_event(event)

        assert changes["event_type"] == "TRADE_PRINT"
        assert "trade" in changes
        assert changes["trade"]["price"] == 100.0

    def test_trade_tape_grows(self, state):
        for i in range(3):
            event = Event(
                event_type=EventType.TRADE_PRINT,
                timestamp=100 + i,
                product="X",
                data={"buyer": "A", "seller": "B", "symbol": "X",
                      "price": 100.0, "quantity": 1},
            )
            state.process_event(event)

        assert len(state.trade_tape) == 3

    def test_trade_tape_capped(self, state):
        for i in range(600):
            event = Event(
                event_type=EventType.TRADE_PRINT,
                timestamp=i,
                product="X",
                data={"buyer": "A", "seller": "B", "symbol": "X",
                      "price": 100.0, "quantity": 1},
            )
            state.process_event(event)

        assert len(state.trade_tape) <= ReplayState.MAX_TAPE_LENGTH


# ======================================================================
# ReplayState reset
# ======================================================================

class TestReplayStateReset:
    def test_reset_clears_all(self, state):
        event = Event(
            event_type=EventType.BOOK_SNAPSHOT,
            timestamp=100,
            product="X",
            data={"day": 1, "bid_prices": [99.0], "bid_volumes": [10],
                  "ask_prices": [101.0], "ask_volumes": [15], "mid_price": 100.0},
        )
        state.process_event(event)
        state.reset()

        assert state.books == {}
        assert state.trade_tape == []
        assert state.positions == {}
        assert state.pnl_history == []
