"""WebSocket endpoint for streaming replay state updates."""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.deps import get_dataset_service, get_replay_engine
from app.services.replay_service import ReplayService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/replay")
async def ws_replay(websocket: WebSocket):
    """Stream replay events over a WebSocket connection.

    The client can send JSON commands:
        {"action": "play"}     - start auto-playing events at current speed
        {"action": "pause"}    - pause auto-play
        {"action": "speed", "value": 5.0}  - change speed
        {"action": "step"}     - step forward one event
        {"action": "step_back"} - step backward one event

    While playing, the server streams events at the configured speed.
    Each outbound message is a JSON object with event + state data.
    """
    await websocket.accept()

    engine = get_replay_engine()
    ds = get_dataset_service()
    svc = ReplayService(engine, ds)

    playing = False
    speed = engine.speed

    async def send_state(data: dict) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    try:
        while True:
            if playing:
                # Auto-play: step forward and stream, with a delay based on speed
                result = svc.step_forward()
                await send_state(result)

                if result.get("done"):
                    playing = False
                    await send_state({"action": "completed"})
                    # Wait for next command
                    msg = await websocket.receive_text()
                    cmd = json.loads(msg)
                    playing, speed = _handle_command(cmd, svc, playing, speed)
                else:
                    # Calculate delay: base delay is ~100ms, divided by speed
                    delay = max(0.001, 0.1 / speed)

                    # Check for incoming commands without blocking for too long
                    try:
                        msg = await asyncio.wait_for(
                            websocket.receive_text(), timeout=delay
                        )
                        cmd = json.loads(msg)
                        playing, speed = _handle_command(cmd, svc, playing, speed)
                    except asyncio.TimeoutError:
                        pass
            else:
                # Paused: wait for commands
                msg = await websocket.receive_text()
                cmd = json.loads(msg)
                playing, speed = _handle_command(cmd, svc, playing, speed)

                # For step commands, send the result back immediately
                action = cmd.get("action", "")
                if action == "step":
                    result = svc.step_forward()
                    await send_state(result)
                elif action == "step_back":
                    result = svc.step_backward()
                    await send_state(result)
                elif action in ("play", "pause", "speed"):
                    await send_state({
                        "action": action,
                        "engine": svc.engine.get_session_state(),
                    })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        try:
            await websocket.close(code=1011, reason=str(exc))
        except Exception:
            pass


def _handle_command(
    cmd: dict,
    svc: ReplayService,
    playing: bool,
    speed: float,
) -> tuple[bool, float]:
    """Process a command from the WebSocket client and return updated state."""
    action = cmd.get("action", "")

    if action == "play":
        svc.engine.play()
        playing = True
    elif action == "pause":
        svc.engine.pause()
        playing = False
    elif action == "speed":
        new_speed = cmd.get("value", speed)
        if isinstance(new_speed, (int, float)) and new_speed > 0:
            speed = float(new_speed)
            svc.set_speed(speed)
    elif action == "step":
        # Handled after this function returns
        playing = False
    elif action == "step_back":
        playing = False

    return playing, speed
