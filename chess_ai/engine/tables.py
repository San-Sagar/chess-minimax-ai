"""Piece values and piece-square tables (PSTs) used by the evaluation function.

All scores are in **centipawns** (100 = one pawn).

Every value comes in two flavours: **middlegame (mg)** and **endgame (eg)**. The
evaluation blends them by game phase ("tapered evaluation"). For example the king
should hide behind its pawns in the middlegame but walk to the centre in the endgame.

Piece values are from Ronald Friederich's PeSTO evaluation. The PSTs are based on Tomasz
Michniewski's "Simplified Evaluation Function" (chessprogramming.org), with separate
endgame tables for pawns and the king.

Tables are written the way you look at the board from White's side: the **first row is
rank 8** and the last row is rank 1, files a to h left to right. See ``pst_index``.
"""

from __future__ import annotations

from chess_ai import chess

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = (
    chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING,
)

# ---------------------------------------------------------------- material

MG_VALUE = {PAWN: 82, KNIGHT: 337, BISHOP: 365, ROOK: 477, QUEEN: 1025, KING: 0}
EG_VALUE = {PAWN: 94, KNIGHT: 281, BISHOP: 297, ROOK: 512, QUEEN: 936, KING: 0}

# ---------------------------------------------------------------- game phase
# Phase 24 = all pieces on the board (pure middlegame), 0 = only kings and pawns.
PHASE_WEIGHT = {PAWN: 0, KNIGHT: 1, BISHOP: 1, ROOK: 2, QUEEN: 4, KING: 0}
MAX_PHASE = 24

# ---------------------------------------------------------------- piece-square tables
# fmt: off
PAWN_MG = [
     0,   0,   0,   0,   0,   0,   0,   0,
    50,  50,  50,  50,  50,  50,  50,  50,
    10,  10,  20,  30,  30,  20,  10,  10,
     5,   5,  10,  25,  25,  10,   5,   5,
     0,   0,   0,  20,  20,   0,   0,   0,
     5,  -5, -10,   0,   0, -10,  -5,   5,
     5,  10,  10, -20, -20,  10,  10,   5,
     0,   0,   0,   0,   0,   0,   0,   0,
]
PAWN_EG = [  # in the endgame pawns are worth more the closer they are to promoting
     0,   0,   0,   0,   0,   0,   0,   0,
    50,  50,  50,  50,  50,  50,  50,  50,
    30,  30,  30,  30,  30,  30,  30,  30,
    20,  20,  20,  20,  20,  20,  20,  20,
    10,  10,  10,  10,  10,  10,  10,  10,
     5,   5,   5,   5,   5,   5,   5,   5,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
]
KNIGHT_PST = [  # knights love the centre, hate the rim
   -50, -40, -30, -30, -30, -30, -40, -50,
   -40, -20,   0,   0,   0,   0, -20, -40,
   -30,   0,  10,  15,  15,  10,   0, -30,
   -30,   5,  15,  20,  20,  15,   5, -30,
   -30,   0,  15,  20,  20,  15,   0, -30,
   -30,   5,  10,  15,  15,  10,   5, -30,
   -40, -20,   0,   5,   5,   0, -20, -40,
   -50, -40, -30, -30, -30, -30, -40, -50,
]
BISHOP_PST = [  # long diagonals, avoid corners
   -20, -10, -10, -10, -10, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,  10,  10,   5,   0, -10,
   -10,   5,   5,  10,  10,   5,   5, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,  10,  10,  10,  10,  10,  10, -10,
   -10,   5,   0,   0,   0,   0,   5, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
]
ROOK_PST = [  # 7th rank is strong, centralise on the back rank
     0,   0,   0,   0,   0,   0,   0,   0,
     5,  10,  10,  10,  10,  10,  10,   5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
     0,   0,   0,   5,   5,   0,   0,   0,
]
QUEEN_PST = [
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,   5,   5,   5,   0,  -5,
     0,   0,   5,   5,   5,   5,   0,  -5,
   -10,   5,   5,   5,   5,   5,   0, -10,
   -10,   0,   5,   0,   0,   0,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
]
KING_MG = [  # middlegame: stay castled behind pawns
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -20, -30, -30, -40, -40, -30, -30, -20,
   -10, -20, -20, -20, -20, -20, -20, -10,
    20,  20,   0,   0,   0,   0,  20,  20,
    20,  30,  10,   0,   0,  10,  30,  20,
]
KING_EG = [  # endgame: the king becomes a fighting piece and goes to the centre
   -50, -40, -30, -20, -20, -30, -40, -50,
   -30, -20, -10,   0,   0, -10, -20, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -30,   0,   0,   0,   0, -30, -30,
   -50, -30, -30, -30, -30, -30, -30, -50,
]
# fmt: on

PST_MG = {PAWN: PAWN_MG, KNIGHT: KNIGHT_PST, BISHOP: BISHOP_PST,
          ROOK: ROOK_PST, QUEEN: QUEEN_PST, KING: KING_MG}
PST_EG = {PAWN: PAWN_EG, KNIGHT: KNIGHT_PST, BISHOP: BISHOP_PST,
          ROOK: ROOK_PST, QUEEN: QUEEN_PST, KING: KING_EG}


def pst_index(square: chess.Square, color: chess.Color) -> int:
    """Index into a table for a piece of ``color`` on ``square``.

    The board numbers squares a1=0 ... h8=63, but tables list rank 8 first.
    For White we flip the rank (``square ^ 56``). Black sees the board from the
    other side, so the un-flipped square already gives the mirrored entry.
    """
    return square ^ 56 if color == chess.WHITE else square
