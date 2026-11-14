"""Phase 0 smoke tests: the package imports and the dependencies work."""

import chess

import chess_ai


def test_package_imports():
    assert chess_ai.__version__ == "0.1.0"


def test_python_chess_starting_position():
    board = chess.Board()
    assert board.legal_moves.count() == 20  # 16 pawn moves + 4 knight moves


def test_backend_dependencies_installed():
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
