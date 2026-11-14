"""The rules of chess, implemented from scratch for this project.

Board representation, move generation, FEN, SAN, game-end rules (``core``) and PGN
reading / writing (``pgn``). Nothing here depends on any outside chess library.

Usage::

    from chess_ai import chess

    board = chess.Board()
    board.push_san("e4")
    print(board.legal_moves.count(), board.fen())
"""

from chess_ai.chess import pgn  # noqa: F401
from chess_ai.chess.core import *  # noqa: F401,F403
from chess_ai.chess.core import (  # noqa: F401  (private helpers used by tests / tools)
    BETWEEN, RAYS, bishop_attacks, queen_attacks, rook_attacks,
)
