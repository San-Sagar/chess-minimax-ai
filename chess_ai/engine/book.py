"""Opening book: known good opening moves, played instantly without searching.

Searching the opening is wasteful: the first moves have been studied for centuries.
The book answers "which moves are known to be good here?" and picks one at random,
weighted by popularity, so the AI does not play the same game every time.

Sources (both optional, combined):

* the **curated book** in ``openings.py`` (always available)
* an external **Polyglot** ``.bin`` book (the standard format used by most chess
  programs) if one is placed at ``data/book.bin``

It also names the opening being played ("Sicilian Defense: Najdorf").
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.polyglot

from chess_ai.engine.openings import BOOK_LINES, OPENING_NAMES

DEFAULT_POLYGLOT = Path(__file__).resolve().parents[2] / "data" / "book.bin"
MAX_BOOK_PLY = 24  # never use the book after this many half-moves


def _key(board: chess.Board):
    return board._transposition_key()


def _play(sequence: str) -> list[chess.Board]:
    """Boards *before* each move of a SAN sequence, plus the final one."""
    board = chess.Board()
    boards = [board.copy()]
    for san in sequence.split():
        board.push_san(san)  # raises ValueError if a curated line is illegal
        boards.append(board.copy())
    return boards


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str

    def to_dict(self) -> dict:
        return {"eco": self.eco, "name": self.name}


@dataclass(frozen=True)
class BookOption:
    move: chess.Move
    san: str
    weight: int
    share: float  # fraction of the total weight in this position

    def to_dict(self) -> dict:
        return {"move": self.move.uci(), "san": self.san, "weight": self.weight,
                "share": round(self.share, 3)}


@dataclass(frozen=True)
class BookProbe:
    """The book's answer for one position."""

    move: chess.Move  # the move picked
    options: list[BookOption]  # all book moves here, most popular first
    source: str  # "curated" or "polyglot"
    opening: Opening | None  # name of the opening *after* the move

    def to_dict(self) -> dict:
        return {"move": self.move.uci(), "source": self.source,
                "options": [o.to_dict() for o in self.options],
                "opening": self.opening.to_dict() if self.opening else None}


class OpeningBook:
    def __init__(self, polyglot_path: str | Path | None = DEFAULT_POLYGLOT,
                 seed: int | None = None, max_ply: int = MAX_BOOK_PLY) -> None:
        self.rng = random.Random(seed)
        self.max_ply = max_ply
        self._moves: dict = defaultdict(lambda: defaultdict(int))  # key -> {uci: weight}
        self._names: dict = {}  # key -> Opening
        for _eco, _name, line, weight in BOOK_LINES:
            boards = _play(line)
            for before, san in zip(boards, line.split()):
                uci = before.parse_san(san).uci()
                self._moves[_key(before)][uci] += weight
        for eco, name, line in OPENING_NAMES:
            self._names[_key(_play(line)[-1])] = Opening(eco, name)
        for eco, name, line, _ in BOOK_LINES:  # full lines carry their variation name
            self._names.setdefault(_key(_play(line)[-1]), Opening(eco, name))

        self.polyglot_path = Path(polyglot_path) if polyglot_path else None
        self._polyglot = None
        if self.polyglot_path and self.polyglot_path.is_file():
            self._polyglot = chess.polyglot.open_reader(self.polyglot_path)

    @property
    def has_polyglot(self) -> bool:
        return self._polyglot is not None

    @property
    def positions(self) -> int:
        """Number of positions in the curated book."""
        return len(self._moves)

    def close(self) -> None:
        if self._polyglot is not None:
            self._polyglot.close()
            self._polyglot = None

    # ------------------------------------------------------------ queries

    def options(self, board: chess.Board) -> tuple[list[BookOption], str]:
        """All book moves for ``board`` (most popular first) and their source."""
        weights: dict[chess.Move, int] = {}
        source = "curated"
        if self._polyglot is not None:
            for entry in self._polyglot.find_all(board):
                if entry.move in board.legal_moves:
                    weights[entry.move] = weights.get(entry.move, 0) + entry.weight
            if weights:
                source = "polyglot"
        if not weights:
            for uci, w in self._moves.get(_key(board), {}).items():
                move = chess.Move.from_uci(uci)
                if move in board.legal_moves:
                    weights[move] = w
        total = sum(weights.values())
        opts = [BookOption(m, board.san(m), w, w / total if total else 0.0)
                for m, w in weights.items() if w > 0]
        opts.sort(key=lambda o: o.weight, reverse=True)
        return opts, source

    def probe(self, board: chess.Board, best: bool = False) -> BookProbe | None:
        """Pick a book move (weighted random, or the most popular if ``best``),
        or None when the position is out of book."""
        if board.ply() >= self.max_ply:
            return None
        opts, source = self.options(board)
        if not opts:
            return None
        if best:
            choice = opts[0]
        else:
            choice = self.rng.choices(opts, weights=[o.weight for o in opts])[0]
        after = board.copy()
        after.push(choice.move)
        return BookProbe(choice.move, opts, source, self.opening_name(after))

    def opening_name(self, board: chess.Board) -> Opening | None:
        """Name of the opening reached by ``board``: the deepest named position in
        its game history (works with transpositions)."""
        b = board.copy()
        while True:
            name = self._names.get(_key(b))
            if name is not None:
                return name
            if not b.move_stack:
                return None
            b.pop()
