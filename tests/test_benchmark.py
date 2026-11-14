"""Tests for the strength-testing tools: puzzles, mate checker, Elo maths."""

import pytest

from chess_ai import chess
from chess_ai.benchmark import PUZZLES, elo_from_score, elo_with_margin, mating_moves
from chess_ai.engine.search import Searcher


@pytest.mark.parametrize("puzzle", PUZZLES, ids=[p.name for p in PUZZLES])
def test_puzzle_positions_are_valid(puzzle):
    board = chess.Board(puzzle.fen)
    assert board.is_valid(), board.status()
    assert puzzle.solutions or puzzle.avoid
    for san in puzzle.solutions + puzzle.avoid:
        board.parse_san(san)  # every listed move is legal


@pytest.mark.parametrize("puzzle", [p for p in PUZZLES if p.mate_in],
                         ids=[p.name for p in PUZZLES if p.mate_in])
def test_mate_puzzles_proven_by_rules_only(puzzle):
    """The answer key equals exactly the set of moves that force mate (brute force)."""
    assert mating_moves(chess.Board(puzzle.fen), puzzle.mate_in) == set(puzzle.solutions)


def test_mate_checker_rejects_stalemate():
    board = chess.Board("7k/8/5K2/8/8/8/8/6R1 w - - 0 1")
    assert "Rg7" not in mating_moves(board, 2)  # stalemate is not mate
    assert mating_moves(board, 1) == set()  # no mate in one here


@pytest.mark.parametrize("puzzle", PUZZLES, ids=[p.name for p in PUZZLES])
def test_engine_solves_every_puzzle(puzzle):
    board = chess.Board(puzzle.fen)
    move = Searcher().search(board, max_depth=6, time_limit=3).best_move
    san = board.san(move)
    if puzzle.solutions:
        assert san in puzzle.solutions
    else:
        assert san not in puzzle.avoid


def test_elo_maths():
    assert elo_from_score(0.5) == pytest.approx(0)
    assert elo_from_score(0.75) == pytest.approx(190.85, abs=0.1)
    assert elo_from_score(0.25) == pytest.approx(-190.85, abs=0.1)
    elo, margin = elo_with_margin(6, 4, 2)
    assert elo > 0 and margin > 0
    elo, margin = elo_with_margin(0, 10, 0)
    assert elo == pytest.approx(0) and margin > 0
