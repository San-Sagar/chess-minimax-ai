"""Perft tests: prove legal move generation matches the published reference counts.

Depths are capped so the whole suite stays fast; scripts/perft.py runs deeper.
"""

import chess
import pytest

from chess_ai.engine.perft import REFERENCE_POSITIONS, divide, perft

MAX_TEST_DEPTH = {"start": 4, "kiwipete": 3, "position3": 4, "position4": 3, "position5": 3}

CASES = [
    (name, depth, expected[depth - 1])
    for name, (_, expected) in REFERENCE_POSITIONS.items()
    for depth in range(1, MAX_TEST_DEPTH[name] + 1)
]


@pytest.mark.parametrize(("name", "depth", "expected"), CASES,
                         ids=[f"{n}-d{d}" for n, d, _ in CASES])
def test_perft_reference(name, depth, expected):
    board = chess.Board(REFERENCE_POSITIONS[name][0])
    assert perft(board, depth) == expected
    assert board.fen() == REFERENCE_POSITIONS[name][0]  # board restored afterwards


def test_divide_sums_to_perft():
    board = chess.Board(REFERENCE_POSITIONS["kiwipete"][0])
    split = divide(board, 2)
    assert len(split) == 48
    assert sum(split.values()) == 2_039


def test_perft_depth_zero():
    assert perft(chess.Board(), 0) == 1
