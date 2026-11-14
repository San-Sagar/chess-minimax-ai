"""Game sessions: everything about one human-vs-AI game kept by the server.

A :class:`GameSession` owns the :class:`~chess_ai.game.Game`, its own
:class:`~chess_ai.engine.engine.Engine` (so transposition tables are per game), the
difficulty :class:`Level`, an optional :class:`Clock`, and the report of every AI move
(search statistics, candidate moves, analysis) for the evaluation and AI Thinking panels.

This module has no web code, so it can be tested directly.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass

from chess_ai import chess
from chess_ai.engine.classic import MATE_SCORE
from chess_ai.engine.engine import Engine
from chess_ai.engine.search import IterationInfo, Searcher, format_score
from chess_ai.engine.tree import record_tree
from chess_ai.explain.narrative import explain_report
from chess_ai.game import BLACK, WHITE, Game, IllegalMoveError


class SessionError(Exception):
    """A request that is valid but not allowed right now (e.g. not your turn)."""


# ----------------------------------------------------------------------- levels


@dataclass(frozen=True)
class Level:
    name: str
    label: str
    description: str
    time_limit: float  # seconds per AI move (upper bound)
    max_depth: int | None  # search depth cap (None = as deep as time allows)
    randomness_cp: int  # may play any candidate within this many centipawns of the best
    use_book: bool
    analysis_time: float  # extra seconds for exact candidate scores (AI Thinking panel)

    def to_dict(self) -> dict:
        return asdict(self)


LEVELS: dict[str, Level] = {lv.name: lv for lv in [
    Level("beginner", "Beginner", "Looks 1 move ahead and often picks a weaker move.",
          0.5, 1, 150, False, 0.4),
    Level("easy", "Easy", "Looks 2 moves ahead, sometimes picks the second-best move.",
          0.8, 2, 60, True, 0.5),
    Level("medium", "Medium", "Searches 4 moves ahead with alpha-beta.",
          1.5, 4, 0, True, 0.8),
    Level("hard", "Hard", "Full engine, 3 seconds per move.", 3.0, None, 0, True, 1.0),
    Level("master", "Master", "Full engine, 8 seconds per move.", 8.0, None, 0, True, 1.5),
]}
DEFAULT_LEVEL = "medium"


# ----------------------------------------------------------------------- clock


class Clock:
    """Chess clock with increment (Fischer). Time is charged when a side moves."""

    def __init__(self, initial_seconds: float, increment: float = 0.0,
                 now: Callable[[], float] = time.monotonic) -> None:
        if initial_seconds <= 0:
            raise ValueError("initial time must be positive")
        self.initial, self.increment, self._now = initial_seconds, increment, now
        self.remaining = {WHITE: float(initial_seconds), BLACK: float(initial_seconds)}
        self.turn = WHITE
        self.started_at: float | None = None  # starts with the first move
        self.stopped = False

    def start(self, turn: str) -> None:
        self.turn, self.started_at = turn, self._now()

    def elapsed(self) -> float:
        if self.started_at is None or self.stopped:
            return 0.0
        return self._now() - self.started_at

    def left(self, color: str) -> float:
        """Seconds left for ``color`` right now."""
        left = self.remaining[color]
        if color == self.turn:
            left -= self.elapsed()
        return left

    def flagged(self) -> str | None:
        """The side whose time has run out, if any."""
        return self.turn if self.left(self.turn) <= 0 else None

    def moved(self, color: str) -> None:
        """``color`` just made a move: charge its time, add increment, switch."""
        if self.started_at is not None:
            self.remaining[color] -= self.elapsed()
            self.remaining[color] += self.increment
        self.turn = BLACK if color == WHITE else WHITE
        self.started_at = self._now()

    def budget(self, color: str) -> float:
        """How long the AI should think: a share of its time plus most of the increment."""
        return max(0.1, self.left(color) / 30 + self.increment * 0.8)

    def to_dict(self) -> dict:
        return {"initial": self.initial, "increment": self.increment,
                "white": round(max(self.left(WHITE), 0), 2),
                "black": round(max(self.left(BLACK), 0), 2),
                "running": self.started_at is not None and not self.stopped,
                "turn": self.turn}


# ----------------------------------------------------------------------- session


def _white_view(score: int | None, mover: str) -> int | None:
    if score is None:
        return None
    return score if mover == WHITE else -score


class GameSession:
    def __init__(self, human_color: str = WHITE, level: str = DEFAULT_LEVEL,
                 fen: str | None = None, clock: Clock | None = None,
                 seed: int | None = None) -> None:
        if human_color not in (WHITE, BLACK):
            raise ValueError("human_color must be 'white' or 'black'")
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}; choose from {list(LEVELS)}")
        self.id = uuid.uuid4().hex[:12]
        self.game = Game(fen) if fen else Game()
        self.human = human_color
        self.ai = BLACK if human_color == WHITE else WHITE
        self.level = LEVELS[level]
        self.engine = Engine(use_book=self.level.use_book, seed=seed)
        self.rng = random.Random(seed)
        self.clock = clock
        if clock is not None:
            clock.turn = self.game.turn
        self.reports: dict[int, dict] = {}  # ply -> full AI move report
        self.evals: dict[int, int | None] = {}  # ply -> score after that ply (White view)
        self.lock = threading.Lock()
        self.thinking = False
        self.last_access = time.monotonic()

    # ------------------------------------------------------------ helpers

    @property
    def ai_to_move(self) -> bool:
        return not self.game.is_over and self.game.turn == self.ai

    def _check_clock(self) -> None:
        if self.clock is not None and not self.game.is_over:
            loser = self.clock.flagged()
            if loser is not None:
                self.game.timeout(loser)
        if self.clock is not None and self.game.is_over:
            self.clock.stopped = True

    def _final_eval(self) -> int | None:
        """Score (White's view) when the game has ended on the board: mate or 0."""
        status = self.game.status()
        if not status.is_over:
            return None
        if status.winner is None:
            return 0
        return MATE_SCORE if status.winner == WHITE else -MATE_SCORE

    def _charge_clock(self, mover: str) -> None:
        if self.clock is not None:
            self.clock.moved(mover)
            if self.clock.remaining[mover] < 0:  # ran out while thinking
                self.game.timeout(mover)
            self._check_clock()

    # ------------------------------------------------------------ state

    def state(self) -> dict:
        self._check_clock()
        last_ply = len(self.game.history)
        last_report = self.reports.get(last_ply)
        return {
            "id": self.id,
            "human_color": self.human,
            "ai_color": self.ai,
            "level": self.level.to_dict(),
            "game": self.game.to_dict(),
            "opening": (o.to_dict() if (o := self.engine.opening_name(self.game.board))
                        else None),
            "evals": [self.evals.get(p) for p in range(1, last_ply + 1)],
            "ai_plies": sorted(self.reports),
            "ai_moves": {str(p): {"source": r["source"], "score_text": r["score_text"],
                                  "seconds": r["seconds"],
                                  "weaker_on_purpose": bool(r.get("difficulty_choice"))}
                         for p, r in self.reports.items()},
            "last_ai_move": _summary(last_report) if last_report else None,
            "ai_to_move": self.ai_to_move,
            "thinking": self.thinking,
            "clock": self.clock.to_dict() if self.clock else None,
        }

    # ------------------------------------------------------------ actions

    def human_move(self, move: str) -> dict:
        with self.lock:
            self._check_clock()
            if self.game.is_over:
                raise SessionError("the game is over")
            if self.thinking or self.game.turn != self.human:
                raise SessionError("it is not your turn")
            rec = self.game.make_move(move)  # IllegalMoveError for bad moves
            if self.clock is not None and self.clock.started_at is None:
                self.clock.start(self.human)
            self._charge_clock(self.human)
            self.evals[rec.ply] = self._final_eval()
            return rec.to_dict()

    def ai_move(self, on_iteration: Callable[[dict], None] | None = None) -> dict:
        """Let the AI move. ``on_iteration`` receives live search updates (dicts)."""
        with self.lock:
            self._check_clock()
            if self.game.is_over:
                raise SessionError("the game is over")
            if self.game.turn != self.ai:
                raise SessionError("it is not the AI's turn")
            self.thinking = True
        try:
            return self._think_and_move(on_iteration)
        finally:
            self.thinking = False

    def _think_and_move(self, on_iteration) -> dict:
        board = self.game.board
        level = self.level
        time_limit = level.time_limit
        if self.clock is not None:
            if self.clock.started_at is None:
                self.clock.start(self.ai)
            time_limit = min(time_limit, self.clock.budget(self.ai))

        def relay(info: IterationInfo) -> None:
            if on_iteration is not None:
                d = info.to_dict()
                d["pv_san"] = _san_line(board, info.pv)
                on_iteration(d)

        reply = self.engine.choose_move(
            board, time_limit=time_limit, max_depth=level.max_depth, analyze=True,
            analysis_time=level.analysis_time, on_iteration=relay)
        report = reply.to_dict()
        played, intended = reply.move, None

        # Lower levels sometimes play a slightly worse candidate on purpose.
        if level.randomness_cp and reply.analysis is not None:
            best = reply.analysis.best.score
            close = [c for c in reply.analysis.candidates
                     if c.score >= best - level.randomness_cp]
            pick = self.rng.choice(close)
            if pick.move != reply.move:
                intended, played = reply.san, pick.move
                report["score"] = pick.score
                report["score_text"] = format_score(pick.score)
        report["difficulty_choice"] = (
            {"intended_san": intended, "played_san": board.san(played),
             "reason": f"{level.label} level plays a weaker move on purpose sometimes"}
            if intended else None)

        with self.lock:
            rec = self.game.make_move(played)
            self._charge_clock(self.ai)
            report.update(ply=rec.ply, san=rec.san, move=rec.uci, fen_before=board.fen(),
                          fen_after=rec.fen_after, level=level.name)
            try:
                report["explanation"] = explain_report(board, report)
            except Exception as exc:  # an explanation bug must never stop the game
                report["explanation"] = {"kind": "error", "headline": rec.san,
                                         "assessment": f"(explanation unavailable: {exc})"}
            self.reports[rec.ply] = report
            score_white = _white_view(report["score"], self.ai)
            final = self._final_eval()
            self.evals[rec.ply] = final if self.game.is_over else score_white
            if rec.ply - 1 >= 1 and self.evals.get(rec.ply - 1) is None and \
                    reply.source == "search" and intended is None:
                # the AI's search score is also its judgement of the human's last move
                self.evals[rec.ply - 1] = score_white
            return report

    def undo(self, plies: int | None = None) -> list[dict]:
        """Take back moves. By default: back to the human's turn, undoing the human's
        last move (and the AI's reply if it already came)."""
        with self.lock:
            if self.thinking:
                raise SessionError("the AI is thinking")
            history = self.game.history
            if plies is None:
                plies = 2 if self.game.turn == self.human else 1
                if history and plies == 2 and len(history) < 2:
                    raise SessionError("nothing of yours to take back")
            if self.game.status().reason == "timeout":
                raise SessionError("cannot take back after a timeout")
            undone = self.game.undo(plies)
            for rec in undone:
                self.reports.pop(rec.ply, None)
                self.evals.pop(rec.ply, None)
            if self.clock is not None:  # time already used stays used; restart the turn
                self.clock.stopped = False
                self.clock.turn = self.game.turn
                if self.clock.started_at is not None:
                    self.clock.started_at = self.clock._now()
            return [r.to_dict() for r in undone]

    def resign(self) -> dict:
        with self.lock:
            return self.game.resign(self.human).to_dict()

    def offer_draw(self, think_time: float = 0.5) -> dict:
        """The AI accepts a draw if it is clearly worse, or (from move 20 on) if it
        does not think it is better. Early in the game it prefers to play on."""
        with self.lock:
            if self.game.is_over:
                raise SessionError("the game is over")
            if self.thinking:
                raise SessionError("the AI is thinking")
            board = self.game.board
            r = Searcher().search(board, time_limit=think_time)
            ai_is_white = self.ai == WHITE
            # r.score is from the side to move's view; convert it to the AI's view
            ai_score = r.score if board.turn == ai_is_white else -r.score
            early = board.fullmove_number < 20
            if ai_score <= -50:
                accepted, reason = True, "The AI thinks it is worse, so it accepts."
            elif early:
                accepted, reason = False, ("It is too early: the AI is not worse, "
                                           "so it wants to play on.")
            elif ai_score <= 25:  # equal (within a quarter pawn)
                accepted, reason = True, "The AI thinks the position is equal, so it accepts."
            else:
                accepted, reason = False, "The AI thinks it is better, so it plays on."
            if accepted:
                self.game.agree_draw()
            return {"accepted": accepted, "ai_score": ai_score,
                    "ai_score_text": format_score(ai_score), "reason": reason}

    # ------------------------------------------------------------ views

    def report(self, ply: int) -> dict:
        if ply not in self.reports:
            raise KeyError(ply)
        return self.reports[ply]

    def tree(self, ply: int | None = None, depth: int = 3, breadth: int = 3) -> dict:
        """Alpha-beta tree for the position before AI move ``ply`` (default: the last
        AI move), following the line the real search expected."""
        if not 1 <= depth <= 4 or not 1 <= breadth <= 5:
            raise ValueError("depth must be 1-4 and breadth 1-5")
        if ply is None:
            if not self.reports:
                raise KeyError("no AI move yet")
            ply = max(self.reports)
        report = self.report(ply)
        board = chess.Board(report["fen_before"])
        pv = []
        analysis = report.get("analysis")
        if analysis:
            pv = [chess.Move.from_uci(u) for u in analysis["best"]["line"]]
        else:
            pv = [chess.Move.from_uci(report["move"])]
        tree = record_tree(board, depth=depth, breadth=breadth, pv=pv)
        return {"ply": ply, **tree.to_dict()}


def _san_line(board: chess.Board, moves: list[chess.Move]) -> list[str]:
    b, out = board.copy(stack=False), []
    for m in moves:
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


def _summary(report: dict) -> dict:
    """A light version of an AI move report (the full one is fetched on demand)."""
    analysis = report.get("analysis") or {}
    return {
        "ply": report["ply"], "san": report["san"], "move": report["move"],
        "source": report["source"], "score": report["score"],
        "score_text": report["score_text"], "mate_in": report.get("mate_in"),
        "seconds": report["seconds"], "opening": report.get("opening"),
        "difficulty_choice": report.get("difficulty_choice"),
        "depth": (analysis.get("search") or {}).get("depth"),
        "nodes": (analysis.get("search") or {}).get("nodes"),
        "best_line": (analysis.get("best") or {}).get("line_san"),
    }


# ----------------------------------------------------------------------- store


class SessionStore:
    """All live games, oldest dropped first when there are too many."""

    def __init__(self, max_sessions: int = 200) -> None:
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, GameSession] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, session: GameSession) -> GameSession:
        with self._lock:
            self._sessions[session.id] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> GameSession:
        with self._lock:
            session = self._sessions[session_id]  # KeyError if unknown
            self._sessions.move_to_end(session_id)
        session.last_access = time.monotonic()
        return session

    def __len__(self) -> int:
        return len(self._sessions)


__all__ = ["Clock", "GameSession", "IllegalMoveError", "LEVELS", "Level", "SessionError",
           "SessionStore"]
