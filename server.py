"""FastAPI WebSocket server for Chinese Checkers."""

import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from game import Game


game = Game()

# Map player_id -> WebSocket
connections: dict[str, WebSocket] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    connections.clear()


app = FastAPI(lifespan=lifespan)


async def broadcast(message: dict, exclude: str | None = None):
    """Send a message to all connected players."""
    text = json.dumps(message)
    for pid, ws in list(connections.items()):
        if pid != exclude:
            try:
                await ws.send_text(text)
            except Exception:
                pass


async def send(ws: WebSocket, message: dict):
    await ws.send_text(json.dumps(message))


async def send_error(ws: WebSocket, message: str):
    await send(ws, {"type": "error", "message": message})


async def handle_create(ws: WebSocket, data: dict) -> str | None:
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    if not name or not password:
        await send_error(ws, "Name and password are required")
        return None

    if game.phase != "idle":
        await send_error(ws, "A game already exists. Stop it first or join it.")
        return None

    player_id = str(uuid.uuid4())
    game.create(name, player_id, password)
    connections[player_id] = ws

    await send(ws, {
        "type": "created",
        "player_id": player_id,
        "password": password,
        "board_definition": game.get_board_definition(),
        "state": game.get_state(),
    })
    return player_id


async def handle_join(ws: WebSocket, data: dict) -> str | None:
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    if not name or not password:
        await send_error(ws, "Name and password are required")
        return None

    try:
        player_id = str(uuid.uuid4())
        game.join(name, player_id, password)
        connections[player_id] = ws

        await send(ws, {
            "type": "joined",
            "player_id": player_id,
            "board_definition": game.get_board_definition(),
            "state": game.get_state(),
        })

        await broadcast({
            "type": "player_joined",
            "state": game.get_state(),
        }, exclude=player_id)

        return player_id
    except ValueError as e:
        await send_error(ws, str(e))
        return None


async def handle_start(ws: WebSocket, player_id: str):
    try:
        game.start(player_id)
        await broadcast({
            "type": "started",
            "state": game.get_state(),
        })
    except ValueError as e:
        await send_error(ws, str(e))


async def handle_get_moves(ws: WebSocket, data: dict, player_id: str):
    row = data.get("row")
    col = data.get("col")
    if row is None or col is None:
        await send_error(ws, "Missing row/col")
        return

    pos = (row, col)
    moves = game.get_valid_moves(pos, player_id)
    await send(ws, {
        "type": "valid_moves",
        "from": [row, col],
        "moves": [[r, c] for r, c in moves],
    })


async def handle_move(ws: WebSocket, data: dict, player_id: str):
    fr = data.get("from")
    to = data.get("to")
    if not fr or not to:
        await send_error(ws, "Missing from/to")
        return

    from_pos = (fr[0], fr[1])
    to_pos = (to[0], to[1])

    try:
        result = game.make_move(from_pos, to_pos, player_id)
        msg = {
            "type": "moved",
            "state": game.get_state(),
        }
        if "winner" in result:
            msg["type"] = "game_over"
            msg["winner_index"] = result["winner"]
            msg["winner_name"] = game.players[result["winner"]]["name"]
        await broadcast(msg)
    except ValueError as e:
        await send_error(ws, str(e))


async def handle_stop(ws: WebSocket, player_id: str):
    if player_id != game.host_id:
        await send_error(ws, "Only the host can stop the game")
        return

    await broadcast({"type": "stopped", "message": "The host stopped the game."})
    game.reset()
    connections.clear()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    player_id = None

    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            msg_type = data.get("type")

            if msg_type == "create":
                player_id = await handle_create(ws, data)

            elif msg_type == "join":
                player_id = await handle_join(ws, data)

            elif msg_type == "start" and player_id:
                await handle_start(ws, player_id)

            elif msg_type == "get_moves" and player_id:
                await handle_get_moves(ws, data, player_id)

            elif msg_type == "move" and player_id:
                await handle_move(ws, data, player_id)

            elif msg_type == "stop" and player_id:
                await handle_stop(ws, player_id)

            else:
                await send_error(ws, f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if player_id:
            connections.pop(player_id, None)
            if game.phase in ("lobby", "playing"):
                game.remove_player(player_id)
                if game.phase == "finished" and game.winner is not None:
                    await broadcast({
                        "type": "game_over",
                        "state": game.get_state(),
                        "winner_index": game.winner,
                        "winner_name": game.players[game.winner]["name"],
                        "reason": "disconnect",
                    })
                else:
                    await broadcast({
                        "type": "player_left",
                        "state": game.get_state(),
                    })


@app.get("/")
async def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
