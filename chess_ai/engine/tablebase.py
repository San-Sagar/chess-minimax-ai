"""Syzygy endgame tablebases: perfect play when few pieces are left.

A tablebase is a precomputed table giving, for **every** position with up to N pieces,
the exact result with perfect play. It is built backwards from all checkmates
(retrograde analysis), which is like a minimax search run to the very end.

Two kinds of tables (files in ``data/syzygy``):

* **WDL** (``.rtbw``): Win / Draw / Loss. ``2`` = win, ``0`` = draw, ``-2`` = loss;
  ``1`` / ``-1`` = a win / loss that the 50-move rule turns into a draw.
* **DTZ** (``.rtbz``): Distance To Zeroing: moves until the next capture or pawn move
  on the fastest winning path. Following it always wins before the 50-move rule.

Used in two places:

* at the **root**: if the position is in the tables, the AI plays the perfect move
  without searching (:meth:`Tablebase.best_move`)
* **inside the search**: right after a capture brings the position into the tables,
  the search uses the exact result instead of guessing with the evaluation
  (:meth:`Tablebase.probe_wdl`).

Everything works without the files; the tablebase is simply unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import chess.syzygy

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "syzygy"

WDL_TEXT = {2: "win", 1: "win, but drawn by the 50-move rule", 0: "draw",
            -1: "loss, but drawn by the 50-move rule", -2: "loss"}


@dataclass(frozen=True)
class TablebaseMove:
    move: chess.Move
    wdl: int  # for the side to move *after* playing this move, from the mover's view
    dtz: int | None  # distance to zeroing after the move (opponent's view), if known
    is_mate: bool
    zeroing: bool  # capture or pawn move (resets the 50-move counter)


@dataclass(frozen=True)
class TablebaseProbe:
    move: chess.Move
    wdl: int  # result for the side to move, with perfect play
    dtz: int | None
    result: str  # "win" / "draw" / "loss" (+ 50-move-rule notes)
    pieces: int
    options: list[TablebaseMove]

    def to_dict(self) -> dict:
        return {"move": self.move.uci(), "wdl": self.wdl, "dtz": self.dtz,
                "result": self.result, "pieces": self.pieces}


class Tablebase:
    def __init__(self, directory: str | Path = DEFAULT_DIR) -> None:
        self.directory = Path(directory)
        self._tb: chess.syzygy.Tablebase | None = None
        self.max_pieces = 0
        if self.directory.is_dir() and any(self.directory.glob("*.rtbw")):
            self._tb = chess.syzygy.open_tablebase(str(self.directory))
            names = [p.stem for p in self.directory.glob("*.rtbw")]
            self.max_pieces = max(len(n.replace("v", "")) for n in names)

    @property
    def available(self) -> bool:
        return self._tb is not None

    def close(self) -> None:
        if self._tb is not None:
            self._tb.close()
            self._tb = None

    def covers(self, board: chess.Board) -> bool:
        """True if ``board`` can be looked up (few enough pieces, no castling rights)."""
        return (self._tb is not None and not board.castling_rights
                and chess.popcount(board.occupied) <= self.max_pieces)

    def probe_wdl(self, board: chess.Board) -> int | None:
        """Win/draw/loss for the side to move, or None if not in the tables."""
        if not self.covers(board):
            return None
        try:
            return self._tb.probe_wdl(board)
        except (KeyError, chess.syzygy.MissingTableError):
            return None

    def probe_dtz(self, board: chess.Board) -> int | None:
        if not self.covers(board):
            return None
        try:
            return self._tb.probe_dtz(board)
        except (KeyError, chess.syzygy.MissingTableError):
            return None

    def best_move(self, board: chess.Board) -> TablebaseProbe | None:
        """The perfect move for ``board``, or None if it is not in the tables.

        * winning: mate if possible, otherwise the move that reaches the next capture
          or pawn move fastest (lowest DTZ), which guarantees the win in time
        * drawing: any move that keeps the draw
        * losing: the move that resists longest (highest DTZ)
        """
        root_wdl = self.probe_wdl(board)
        if root_wdl is None or board.is_game_over():
            return None
        options = []
        for move in board.legal_moves:
            zeroing = board.is_zeroing(move)
            board.push(move)
            if board.is_checkmate():
                options.append(TablebaseMove(move, 2, 0, True, zeroing))
                board.pop()
                continue
            wdl = self.probe_wdl(board)
            dtz = self.probe_dtz(board)
            board.pop()
            if wdl is None:
                return None  # a needed table is missing: let the search decide
            options.append(TablebaseMove(move, -wdl, dtz, False, zeroing))

        def rank(o: TablebaseMove):
            dtz = abs(o.dtz) if o.dtz is not None else 1000
            if o.wdl > 0:  # winning: mate first, then fastest progress
                return (o.wdl, 1 if o.is_mate else 0, 1 if o.zeroing else 0, -dtz)
            if o.wdl < 0:  # losing: hold out as long as possible
                return (o.wdl, 0, 0, dtz)
            return (0, 0, 0, 0)

        options.sort(key=rank, reverse=True)
        best = options[0]
        return TablebaseProbe(
            move=best.move, wdl=root_wdl, dtz=self.probe_dtz(board),
            result=WDL_TEXT[root_wdl], pieces=chess.popcount(board.occupied),
            options=options,
        )
