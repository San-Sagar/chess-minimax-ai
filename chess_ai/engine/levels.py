"""Difficulty levels: how deep the AI searches and how often it plays a weaker move.

Used by the web server (human vs AI) and by the strength-testing scripts (AI vs AI),
so both play exactly the same way.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import asdict, dataclass

from chess_ai import chess
from chess_ai.engine.engine import Engine, EngineMove
from chess_ai.engine.search import IterationInfo


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


@dataclass
class LevelMove:
    reply: EngineMove  # what the engine found
    played: chess.Move  # what is actually played (may be a weaker candidate)
    intended_san: str | None  # the engine's best move, if a weaker one was played


def play_level_move(
    engine: Engine,
    board: chess.Board,
    level: Level,
    rng: random.Random,
    time_limit: float | None = None,
    analyze: bool = True,
    on_iteration: Callable[[IterationInfo], None] | None = None,
) -> LevelMove:
    """Choose a move the way ``level`` plays.

    ``time_limit`` overrides the level's own (e.g. when a clock leaves less time).
    Levels with randomness always analyse, because they choose among the exact-scored
    candidate moves.
    """
    limit = level.time_limit if time_limit is None else min(time_limit, level.time_limit)
    need_analysis = analyze or level.randomness_cp > 0
    reply = engine.choose_move(board, time_limit=limit, max_depth=level.max_depth,
                               analyze=need_analysis, analysis_time=level.analysis_time,
                               on_iteration=on_iteration)
    played, intended = reply.move, None
    if level.randomness_cp and reply.analysis is not None:
        best = reply.analysis.best.score
        close = [c for c in reply.analysis.candidates if c.score >= best - level.randomness_cp]
        pick = rng.choice(close)
        if pick.move != reply.move:
            played, intended = pick.move, reply.san
    return LevelMove(reply, played, intended)
