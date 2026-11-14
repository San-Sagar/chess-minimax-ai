"""The complete AI player: opening book -> endgame tablebase -> minimax search.

This is what the server (and anything else that wants a move) talks to:

>>> engine = Engine()
>>> reply = engine.choose_move(board, time_limit=3.0)
>>> reply.move, reply.source, reply.score_text

For every move it reports **where the move came from**:

* ``"book"``: a known opening move, played instantly
* ``"tablebase"``: a perfect endgame move from the Syzygy tables
* ``"search"``: found by the minimax / alpha-beta search (with full analysis for the
  AI Thinking panel when ``analyze=True``)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import chess

from chess_ai.engine.analysis import MoveAnalysis, analyze_move
from chess_ai.engine.book import DEFAULT_POLYGLOT, BookProbe, Opening, OpeningBook
from chess_ai.engine.search import (
    TB_WIN, IterationInfo, SearchConfig, SearchResult, Searcher, format_score, mate_in,
)
from chess_ai.engine.tablebase import DEFAULT_DIR, Tablebase, TablebaseProbe


@dataclass
class EngineMove:
    move: chess.Move
    san: str
    source: str  # "book", "tablebase" or "search"
    score: int | None  # AI's point of view; None for book moves (not evaluated)
    seconds: float
    opening: Opening | None = None  # name of the opening after this move, if known
    book: BookProbe | None = None
    tablebase: TablebaseProbe | None = None
    search: SearchResult | None = None
    analysis: MoveAnalysis | None = None

    @property
    def score_text(self) -> str | None:
        return format_score(self.score) if self.score is not None else None

    def to_dict(self) -> dict:
        return {
            "move": self.move.uci(), "san": self.san, "source": self.source,
            "score": self.score, "score_text": self.score_text,
            "mate_in": mate_in(self.score) if self.score is not None else None,
            "seconds": round(self.seconds, 3),
            "opening": self.opening.to_dict() if self.opening else None,
            "book": self.book.to_dict() if self.book else None,
            "tablebase": self.tablebase.to_dict() if self.tablebase else None,
            "search": [i.to_dict() for i in self.search.iterations] if self.search else None,
            "analysis": self.analysis.to_dict() if self.analysis else None,
        }


class Engine:
    def __init__(
        self,
        config: SearchConfig | None = None,
        use_book: bool = True,
        use_tablebase: bool = True,
        book_path: str | Path | None = DEFAULT_POLYGLOT,
        tablebase_dir: str | Path = DEFAULT_DIR,
        seed: int | None = None,
    ) -> None:
        self.book = OpeningBook(book_path, seed=seed) if use_book else None
        self.tablebase = Tablebase(tablebase_dir) if use_tablebase else None
        self.searcher = Searcher(config, tablebase=self.tablebase)

    def new_game(self) -> None:
        self.searcher.new_game()

    def close(self) -> None:
        if self.book:
            self.book.close()
        if self.tablebase:
            self.tablebase.close()

    def info(self) -> dict:
        return {
            "book_positions": self.book.positions if self.book else 0,
            "polyglot_book": bool(self.book and self.book.has_polyglot),
            "tablebase": bool(self.tablebase and self.tablebase.available),
            "tablebase_pieces": self.tablebase.max_pieces if self.tablebase else 0,
        }

    def opening_name(self, board: chess.Board) -> Opening | None:
        return self.book.opening_name(board) if self.book else None

    def choose_move(
        self,
        board: chess.Board,
        time_limit: float | None = 3.0,
        max_depth: int | None = None,
        analyze: bool = True,
        analysis_time: float = 1.0,
        on_iteration: Callable[[IterationInfo], None] | None = None,
    ) -> EngineMove:
        """Pick a move for the side to move in ``board``."""
        if board.is_game_over():
            raise ValueError("the game is over")
        start = time.perf_counter()

        # 1. Opening book
        if self.book is not None:
            probe = self.book.probe(board)
            if probe is not None:
                return EngineMove(probe.move, board.san(probe.move), "book", None,
                                  time.perf_counter() - start, opening=probe.opening,
                                  book=probe)

        # 2. Endgame tablebase
        if self.tablebase is not None and self.tablebase.available:
            tb = self.tablebase.best_move(board)
            if tb is not None:
                score = TB_WIN if tb.wdl >= 2 else -TB_WIN if tb.wdl <= -2 else 0
                return EngineMove(tb.move, board.san(tb.move), "tablebase", score,
                                  time.perf_counter() - start, tablebase=tb,
                                  opening=self.opening_name(board))

        # 3. Minimax / alpha-beta search
        result = self.searcher.search(board, max_depth=max_depth, time_limit=time_limit,
                                      on_iteration=on_iteration)
        analysis = None
        if analyze:
            analysis = analyze_move(board, result, self.searcher, top_n=3,
                                    time_limit=analysis_time)
        after = board.copy()
        after.push(result.best_move)
        return EngineMove(result.best_move, board.san(result.best_move), "search",
                          result.score, time.perf_counter() - start,
                          opening=self.opening_name(after), search=result,
                          analysis=analysis)
