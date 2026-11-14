"""Perft ("performance test"): count every position reachable in N moves.

Perft is the standard way to prove a chess move generator is correct: the exact counts
for well-known test positions are published, and any bug in castling, en passant,
promotion, pins or checks makes the numbers differ. It also measures raw speed
(nodes per second), which limits how deep the minimax search can look.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from chess_ai import chess


def perft(board: chess.Board, depth: int) -> int:
    """Number of leaf positions after exactly ``depth`` plies from ``board``."""
    if depth == 0:
        return 1
    if depth == 1:  # "bulk counting": no need to play the last move
        return board.legal_moves.count()
    nodes = 0
    for move in board.legal_moves:
        board.push(move)
        nodes += perft(board, depth - 1)
        board.pop()
    return nodes


def divide(board: chess.Board, depth: int) -> dict[str, int]:
    """Perft split per first move. Comparing this with a reference engine pinpoints
    exactly which move a generator bug is under."""
    if depth < 1:
        raise ValueError("depth must be >= 1")
    result = {}
    for move in board.legal_moves:
        board.push(move)
        result[move.uci()] = perft(board, depth - 1)
        board.pop()
    return result


@dataclass(frozen=True)
class PerftResult:
    depth: int
    nodes: int
    seconds: float

    @property
    def nodes_per_second(self) -> float:
        return self.nodes / self.seconds if self.seconds > 0 else float("inf")


def timed_perft(board: chess.Board, depth: int) -> PerftResult:
    start = time.perf_counter()
    nodes = perft(board, depth)
    return PerftResult(depth, nodes, time.perf_counter() - start)


# Standard test positions with published node counts (chessprogramming.org "Perft Results").
# {name: (fen, [count at depth 1, depth 2, ...])}
REFERENCE_POSITIONS: dict[str, tuple[str, list[int]]] = {
    "start": (chess.STARTING_FEN, [20, 400, 8_902, 197_281, 4_865_609]),
    "kiwipete": (  # castling, pins, en passant, promotions all at once
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        [48, 2_039, 97_862, 4_085_603],
    ),
    "position3": (  # en passant edge cases, discovered checks
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        [14, 191, 2_812, 43_238, 674_624],
    ),
    "position4": (  # promotions, castling rights lost by captures
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        [6, 264, 9_467, 422_333],
    ),
    "position5": (
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        [44, 1_486, 62_379, 2_103_487],
    ),
}
