"""Strength testing: tactical puzzles, a rules-only mate checker, and Elo maths.

Puzzles
-------
Each puzzle is a position plus the move(s) that solve it (or, for "avoid" puzzles, the
tempting move that must NOT be played). Mate puzzles are proven by
:func:`mating_moves`, a brute-force search that uses only the rules of chess (no
evaluation function), so their answers do not depend on our AI at all.

Elo
---
:func:`elo_from_score` turns a match score into a rating difference, with a 95% error
margin, using the standard logistic Elo model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from chess_ai import chess


@dataclass(frozen=True)
class Puzzle:
    name: str
    theme: str  # "mate", "fork", "skewer", ...
    fen: str
    solutions: tuple[str, ...] = ()  # SAN of every correct first move
    avoid: tuple[str, ...] = ()  # SAN of tempting moves that lose
    mate_in: int | None = None  # for mate puzzles: proven by mating_moves()
    note: str = ""


PUZZLES: list[Puzzle] = [
    # ------------------------------------------------------------ checkmates
    Puzzle("Back-rank mate", "mate", "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1",
           ("Ra8#",), mate_in=1, note="The king is trapped behind its own pawns."),
    Puzzle("Smothered mate", "mate", "6rk/6pp/8/6N1/8/8/8/6K1 w - - 0 1",
           ("Nf7#",), mate_in=1, note="The king is boxed in by its own pieces."),
    Puzzle("Queen mate with king support", "mate", "7k/8/6K1/8/8/8/8/5Q2 w - - 0 1",
           ("Qf8#",), mate_in=1),
    Puzzle("Mate by promotion", "mate", "k7/2P5/1K6/8/8/8/8/8 w - - 0 1",
           ("c8=Q#", "c8=R#"), mate_in=1),
    Puzzle("Long-range queen mate", "mate", "k7/8/1K6/8/8/8/7Q/8 w - - 0 1",
           ("Qh8#",), mate_in=1),
    Puzzle("Rook ladder", "mate", "7k/8/8/8/8/8/R7/1R4K1 w - - 0 1",
           ("Ra7", "Rb7"), mate_in=2, note="One rook cuts the king off, the other mates."),
    Puzzle("Quiet king move, then mate", "mate", "7k/8/5K2/8/8/8/8/6R1 w - - 0 1",
           ("Kf7",), mate_in=2, note="Rg7?? would be stalemate."),
    # ------------------------------------------------------------ winning material
    Puzzle("Free queen", "hanging piece", "4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1", ("Rxd5",)),
    Puzzle("Knight fork", "fork", "r3k3/8/8/1N6/8/8/P7/4K3 w - - 0 1", ("Nc7+",),
           note="Check and attack on the rook at the same time."),
    Puzzle("Pawn fork", "fork", "4k3/8/8/2n1b3/8/2PP4/8/4K3 w - - 0 1", ("d4",),
           note="The pawn attacks knight and bishop; c3 protects it."),
    Puzzle("Skewer", "skewer", "1q6/8/8/8/1k6/8/8/K6R w - - 0 1", ("Rb1+",),
           note="The king must step aside and the queen behind it falls."),
    Puzzle("Discovered check", "discovered attack", "3k4/8/1q6/8/8/8/3N4/3RK3 w - - 0 1",
           ("Nc4+",), note="The knight uncovers check from the rook and attacks the queen."),
    Puzzle("Promote the pawn", "promotion", "8/1P6/8/8/8/8/6k1/K7 w - - 0 1", ("b8=Q",)),
    # ------------------------------------------------------------ traps to avoid
    Puzzle("Poisoned pawn", "avoid", "4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1", avoid=("Qxd5",),
           note="Qxd5?? exd5 loses the queen (the horizon effect)."),
    Puzzle("Do not stalemate", "avoid", "7k/8/5K2/8/8/8/8/6R1 w - - 0 1", avoid=("Rg7",),
           note="Rg7 leaves Black no legal move: stalemate, a draw."),
]


# ---------------------------------------------------------------------- mate checker


def _forces_mate(board: chess.Board, n: int) -> bool:
    """Can the side to move force checkmate within ``n`` of its own moves?"""
    for move in list(board.legal_moves):
        board.push(move)
        try:
            if _move_mates(board, n):
                return True
        finally:
            board.pop()
    return False


def _move_mates(board: chess.Board, n: int) -> bool:
    """After our move (opponent to move now): is it mate, or mate in n-1 against
    every reply?"""
    replies = list(board.legal_moves)
    if not replies:
        return board.is_check()  # checkmate (stalemate is not a win)
    if n <= 1:
        return False
    for reply in replies:
        board.push(reply)
        try:
            if not _forces_mate(board, n - 1):
                return False
        finally:
            board.pop()
    return True


def mating_moves(board: chess.Board, n: int) -> set[str]:
    """SAN of every first move that forces mate in at most ``n`` moves (rules only)."""
    b = board.copy()
    out = set()
    for move in list(b.legal_moves):
        san = b.san(move)
        b.push(move)
        if _move_mates(b, n):
            out.add(san)
        b.pop()
    return out


# ---------------------------------------------------------------------- Elo


@dataclass
class MatchScore:
    wins: int = 0
    draws: int = 0
    losses: int = 0
    games: list[dict] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.wins + self.draws + self.losses

    @property
    def score(self) -> float:
        return (self.wins + 0.5 * self.draws) / self.n if self.n else 0.5


def elo_from_score(score: float) -> float:
    """Rating difference implied by an expected score (0..1)."""
    score = min(max(score, 1e-3), 1 - 1e-3)
    return -400 * math.log10(1 / score - 1)


def elo_with_margin(wins: int, draws: int, losses: int) -> tuple[float, float]:
    """(Elo difference, 95% margin) from a match result."""
    n = wins + draws + losses
    if n == 0:
        return 0.0, float("inf")
    s = (wins + 0.5 * draws) / n
    # standard deviation of the per-game score
    var = (wins * (1 - s) ** 2 + draws * (0.5 - s) ** 2 + losses * (0 - s) ** 2) / n
    se = math.sqrt(var / n) if var > 0 else 0.5 / math.sqrt(n)
    lo, hi = elo_from_score(s - 1.96 * se), elo_from_score(s + 1.96 * se)
    return elo_from_score(s), (hi - lo) / 2
