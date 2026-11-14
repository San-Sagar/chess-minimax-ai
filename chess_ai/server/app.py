"""The web server: REST API + WebSocket for the human-vs-AI game.

Run it with::

    .venv\\Scripts\\python -m chess_ai.server        # http://127.0.0.1:8000

REST (JSON)
-----------
GET  /api/health                         server is up
GET  /api/info                           difficulty levels, engine facts
POST /api/games                          new game {human_color, level, fen?, clock...}
GET  /api/games/{id}                     full game state
POST /api/games/{id}/move                your move {move: "e2e4" or "e4"}
POST /api/games/{id}/ai-move             AI moves (waits for the whole search)
POST /api/games/{id}/undo                take back {plies?}
POST /api/games/{id}/resign
POST /api/games/{id}/draw                offer a draw: the AI accepts or declines
GET  /api/games/{id}/pgn                 the game as PGN text
GET  /api/games/{id}/analysis/{ply}      everything recorded about AI move ``ply``
GET  /api/games/{id}/tree?ply&depth&breadth   alpha-beta tree for the search viewer
POST /api/evaluate                       evaluation breakdown of any FEN

WebSocket
---------
/ws/games/{id}: send ``{"type": "ai_move"}``; the server answers with
``thinking_started``, one ``iteration`` message per completed search depth (live
evaluation panel), then ``ai_move`` (the report + the new state) or ``error``.

The web page in ``web/`` is served at ``/`` when it exists.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chess_ai import __version__, chess
from chess_ai.engine.evaluation import evaluate_breakdown
from chess_ai.game import BLACK, WHITE, IllegalMoveError
from chess_ai.server.sessions import (
    DEFAULT_LEVEL, LEVELS, Clock, GameSession, SessionError, SessionStore,
)

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="Chess Minimax AI", version=__version__,
              description="Play chess against a minimax / alpha-beta AI and see why it moves.")
store = SessionStore()


# ----------------------------------------------------------------------- models


class NewGame(BaseModel):
    human_color: Literal["white", "black", "random"] = "white"
    level: str = DEFAULT_LEVEL
    fen: str | None = None
    clock_minutes: float | None = Field(None, gt=0, le=180)
    increment_seconds: float = Field(0, ge=0, le=60)


class MoveIn(BaseModel):
    move: str


class UndoIn(BaseModel):
    plies: int | None = Field(None, ge=1)


class EvaluateIn(BaseModel):
    fen: str


# ----------------------------------------------------------------------- helpers


def _session(game_id: str) -> GameSession:
    try:
        return store.get(game_id)
    except KeyError:
        raise HTTPException(404, f"no game {game_id!r}") from None


def _run(fn, *args, **kwargs):
    """Call a session action, mapping errors to HTTP status codes."""
    try:
        return fn(*args, **kwargs)
    except IllegalMoveError as exc:
        raise HTTPException(400, str(exc)) from None
    except SessionError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


# ----------------------------------------------------------------------- REST


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "games": len(store)}


@app.get("/api/info")
def info() -> dict:
    return {
        "version": __version__,
        "levels": [lv.to_dict() for lv in LEVELS.values()],
        "default_level": DEFAULT_LEVEL,
        "rules_engine": "chess_ai.chess (written from scratch)",
        "search": "negamax minimax with alpha-beta pruning, iterative deepening, "
                  "quiescence, move ordering, transposition table, PVS, null-move, "
                  "late-move reductions, futility pruning",
    }


@app.post("/api/games", status_code=201)
def new_game(req: NewGame) -> dict:
    color = req.human_color if req.human_color != "random" else random.choice([WHITE, BLACK])
    clock = Clock(req.clock_minutes * 60, req.increment_seconds) if req.clock_minutes else None
    try:
        session = GameSession(human_color=color, level=req.level, fen=req.fen, clock=clock)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    store.add(session)
    return session.state()


@app.get("/api/games/{game_id}")
def get_game(game_id: str) -> dict:
    return _session(game_id).state()


@app.post("/api/games/{game_id}/move")
def human_move(game_id: str, req: MoveIn) -> dict:
    s = _session(game_id)
    record = _run(s.human_move, req.move)
    return {"move": record, "state": s.state()}


@app.post("/api/games/{game_id}/ai-move")
async def ai_move(game_id: str) -> dict:
    s = _session(game_id)
    report = await asyncio.to_thread(_run, s.ai_move)  # keep the server responsive
    return {"report": report, "state": s.state()}


@app.post("/api/games/{game_id}/undo")
def undo(game_id: str, req: UndoIn | None = None) -> dict:
    s = _session(game_id)
    undone = _run(s.undo, req.plies if req else None)
    return {"undone": undone, "state": s.state()}


@app.post("/api/games/{game_id}/resign")
def resign(game_id: str) -> dict:
    s = _session(game_id)
    _run(s.resign)
    return {"state": s.state()}


@app.post("/api/games/{game_id}/draw")
async def offer_draw(game_id: str) -> dict:
    s = _session(game_id)
    answer = await asyncio.to_thread(_run, s.offer_draw)
    return {"answer": answer, "state": s.state()}


@app.get("/api/games/{game_id}/pgn", response_class=PlainTextResponse)
def pgn(game_id: str) -> str:
    s = _session(game_id)
    you, ai = "You", f"Chess Minimax AI ({s.level.label})"
    return s.game.to_pgn(white=you if s.human == WHITE else ai,
                         black=you if s.human == BLACK else ai)


@app.get("/api/games/{game_id}/analysis/{ply}")
def analysis(game_id: str, ply: int) -> dict:
    s = _session(game_id)
    try:
        return s.report(ply)
    except KeyError:
        raise HTTPException(404, f"no AI move at ply {ply}") from None


@app.get("/api/games/{game_id}/tree")
async def tree(game_id: str, ply: int | None = None, depth: int = 3, breadth: int = 3) -> dict:
    s = _session(game_id)
    try:
        return await asyncio.to_thread(s.tree, ply, depth, breadth)
    except KeyError:
        raise HTTPException(404, "no AI move to show a tree for") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/evaluate")
def evaluate_position(req: EvaluateIn) -> dict:
    try:
        board = chess.Board(req.fen)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"fen": board.fen(), **evaluate_breakdown(board).to_dict()}


# ----------------------------------------------------------------------- WebSocket


@app.websocket("/ws/games/{game_id}")
async def game_socket(websocket: WebSocket, game_id: str) -> None:
    await websocket.accept()
    try:
        session = store.get(game_id)
    except KeyError:
        await websocket.send_json({"type": "error", "message": f"no game {game_id!r}"})
        await websocket.close(code=4404)
        return
    loop = asyncio.get_running_loop()
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "ai_move":
                await websocket.send_json({"type": "error",
                                           "message": "unknown message type"})
                continue
            queue: asyncio.Queue = asyncio.Queue()

            def on_iteration(data: dict) -> None:  # called from the search thread
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "iteration", "data": data})

            def think():
                try:
                    return session.ai_move(on_iteration)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # end marker

            await websocket.send_json({"type": "thinking_started"})
            task = asyncio.create_task(asyncio.to_thread(think))
            while (item := await queue.get()) is not None:
                await websocket.send_json(item)
            try:
                report = await task
            except (SessionError, IllegalMoveError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue
            await websocket.send_json({"type": "ai_move", "report": report,
                                       "state": session.state()})
    except WebSocketDisconnect:
        return


# ----------------------------------------------------------------------- web page

if (WEB_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
