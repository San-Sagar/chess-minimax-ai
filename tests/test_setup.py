"""Phase 0 smoke tests: the package imports and the dependencies work."""

import importlib.util

import chess_ai
from chess_ai import chess


def test_no_outside_chess_library():
    """The project implements chess itself: python-chess must not be installed/used."""
    assert importlib.util.find_spec("chess") is None
    assert chess.__name__ == "chess_ai.chess"


def test_package_imports():
    assert chess_ai.__version__ == "0.1.0"


def test_python_chess_starting_position():
    board = chess.Board()
    assert board.legal_moves.count() == 20  # 16 pawn moves + 4 knight moves


def test_backend_dependencies_installed():
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
