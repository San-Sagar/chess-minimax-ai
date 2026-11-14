"""The evaluation function: how the AI judges a position without searching further.

Minimax searches a few moves ahead; at the end of each line ("leaf" positions) it
calls :func:`evaluate` to get a single number. Positive means the side to move is
better (this "negamax" convention lets one search function play both colours).

The score is the sum of these **terms**, each computed separately for White and Black:

==================  ==========================================================
material            piece values (pawn ~ 1, knight/bishop ~ 3, rook ~ 5, queen ~ 10)
piece_squares       where pieces stand: knights in the centre, king tucked away...
pawn_structure      penalties for doubled and isolated pawns
passed_pawns        bonus for pawns no enemy pawn can stop, bigger as they advance
mobility            how many safe squares the pieces can move to
king_safety         pawn shield, open files near the king, enemy attacks on it
bishop_pair         bonus for keeping both bishops
rook_files          rooks on open or half-open files
tempo               small bonus for having the move
==================  ==========================================================

Every term has a middlegame and an endgame value, blended by game phase
(**tapered evaluation**): phase 24 means all pieces are on the board, 0 means only
kings and pawns are left.

:func:`evaluate_breakdown` returns the same score split into terms. The AI Thinking
panel uses it to explain moves, e.g. "this move improves king safety by +0.4".
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_ai import chess

from chess_ai.engine.tables import (
    BISHOP, EG_VALUE, KING, KNIGHT, MAX_PHASE, MG_VALUE, PAWN, PHASE_WEIGHT,
    PST_EG, PST_MG, QUEEN, ROOK, pst_index,
)

TERMS = (
    "material", "piece_squares", "pawn_structure", "passed_pawns", "mobility",
    "king_safety", "bishop_pair", "rook_files", "tempo",
)

TERM_LABELS = {
    "material": "Material",
    "piece_squares": "Piece placement",
    "pawn_structure": "Pawn structure",
    "passed_pawns": "Passed pawns",
    "mobility": "Mobility",
    "king_safety": "King safety",
    "bishop_pair": "Bishop pair",
    "rook_files": "Rooks on open files",
    "tempo": "Side to move",
}

# ---------------------------------------------------------------- tuning constants
# All (middlegame, endgame) in centipawns.

DOUBLED_PAWN = (-10, -20)  # per extra pawn on the same file
ISOLATED_PAWN = (-15, -20)  # per pawn with no friendly pawn on neighbouring files
PASSED_PAWN_MG = (0, 5, 10, 15, 25, 40, 60, 0)  # by rank from the pawn's own side (0-7)
PASSED_PAWN_EG = (0, 10, 20, 35, 60, 100, 150, 0)

# Mobility: (mg weight, eg weight, typical number of moves). Scores count moves above
# or below "typical", so a normally placed piece scores about zero.
MOBILITY = {
    KNIGHT: (4, 4, 4),
    BISHOP: (5, 5, 6),
    ROOK: (2, 4, 6),
    QUEEN: (1, 2, 12),
}

SHIELD_PAWN_ADVANCED = -10  # shield pawn has moved one square forward
SHIELD_PAWN_MISSING = -25
KING_FILE_HALF_OPEN = -15  # no friendly pawn on a file next to the king
KING_FILE_OPEN = -10  # ...and no enemy pawn either (extra)
# Penalty by number of enemy attacks on the squares around the king.
KING_ATTACK_PENALTY = (0, 0, 8, 20, 35, 55, 80, 110, 140, 175, 210, 250, 290, 330, 370, 400)

BISHOP_PAIR = (30, 50)
ROOK_OPEN_FILE = (25, 10)
ROOK_HALF_OPEN_FILE = (12, 5)
TEMPO = (10, 0)

# ---------------------------------------------------------------- precomputed masks

_ADJACENT_FILES = [
    (chess.BB_FILES[f - 1] if f > 0 else 0) | (chess.BB_FILES[f + 1] if f < 7 else 0)
    for f in range(8)
]


def _passed_mask(square: chess.Square, color: chess.Color) -> int:
    """Squares in front of a pawn (own and neighbouring files) that enemy pawns
    must not occupy for the pawn to be 'passed'."""
    file, rank = chess.square_file(square), chess.square_rank(square)
    files = chess.BB_FILES[file] | _ADJACENT_FILES[file]
    ahead = 0
    ranks = range(rank + 1, 8) if color == chess.WHITE else range(0, rank)
    for r in ranks:
        ahead |= chess.BB_RANKS[r]
    return files & ahead


_PASSED_MASKS = {c: [_passed_mask(sq, c) for sq in chess.SQUARES] for c in chess.COLORS}


def _pawn_attacks(pawns: int, color: chess.Color) -> int:
    """All squares attacked by a set of pawns of ``color``."""
    if color == chess.WHITE:
        return (((pawns << 7) & ~chess.BB_FILE_H) | ((pawns << 9) & ~chess.BB_FILE_A)) \
            & chess.BB_ALL
    return ((pawns >> 7) & ~chess.BB_FILE_A) | ((pawns >> 9) & ~chess.BB_FILE_H)


# ---------------------------------------------------------------- the terms


def game_phase(board: chess.Board) -> int:
    """24 = opening/middlegame with all pieces, 0 = pawn endgame."""
    phase = 0
    for pt in (KNIGHT, BISHOP, ROOK, QUEEN):
        phase += PHASE_WEIGHT[pt] * chess.popcount(board.pieces_mask(pt, chess.WHITE)
                                                   | board.pieces_mask(pt, chess.BLACK))
    return min(phase, MAX_PHASE)


def _pawn_attack_count(pawns: int, color: chess.Color, target: int) -> int:
    """Number of (pawn, attacked square) pairs landing on ``target``."""
    if color == chess.WHITE:
        left = (pawns << 7) & ~chess.BB_FILE_H & chess.BB_ALL
        right = (pawns << 9) & ~chess.BB_FILE_A & chess.BB_ALL
    else:
        left = (pawns >> 9) & ~chess.BB_FILE_H
        right = (pawns >> 7) & ~chess.BB_FILE_A
    return chess.popcount(left & target) + chess.popcount(right & target)


def _king_attack_penalty(attacks: int, attacker_has_queen: bool) -> int:
    penalty = KING_ATTACK_PENALTY[min(attacks, len(KING_ATTACK_PENALTY) - 1)]
    return penalty if attacker_has_queen else penalty // 2  # far less dangerous w/o queen


def _side_terms(
    board: chess.Board, color: chess.Color
) -> tuple[dict[str, tuple[int, int]], int]:
    """Every term for one side, as (middlegame, endgame) pairs, plus the number of
    attacks this side makes on the squares around the *enemy* king (the caller turns
    that into the enemy's king-safety penalty; it falls out of the mobility loop
    for free, which is much faster than asking 'who attacks this square?' 9 times)."""
    them = not color
    our_pawns = board.pieces_mask(PAWN, color)
    their_pawns = board.pieces_mask(PAWN, them)
    own_pieces = board.occupied_co[color]
    unsafe = _pawn_attacks(their_pawns, them)  # squares guarded by enemy pawns
    enemy_king = board.king(them)
    enemy_zone = (chess.BB_KING_ATTACKS[enemy_king] | chess.BB_SQUARES[enemy_king]
                  if enemy_king is not None else 0)
    pressure = _pawn_attack_count(our_pawns, color, enemy_zone)

    mat_mg = mat_eg = pst_mg = pst_eg = mob_mg = mob_eg = 0
    rook_mg = rook_eg = 0

    for pt in (PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING):
        mask = board.pieces_mask(pt, color)
        if not mask:
            continue
        count = chess.popcount(mask)
        mat_mg += MG_VALUE[pt] * count
        mat_eg += EG_VALUE[pt] * count
        mg_table, eg_table, mobility = PST_MG[pt], PST_EG[pt], MOBILITY.get(pt)
        for sq in chess.scan_forward(mask):
            idx = pst_index(sq, color)
            pst_mg += mg_table[idx]
            pst_eg += eg_table[idx]
            if mobility:
                attacks = board.attacks_mask(sq)
                pressure += chess.popcount(attacks & enemy_zone)
                moves = chess.popcount(attacks & ~own_pieces & ~unsafe)
                w_mg, w_eg, typical = mobility
                mob_mg += (moves - typical) * w_mg
                mob_eg += (moves - typical) * w_eg
            elif pt == KING:
                pressure += chess.popcount(chess.BB_KING_ATTACKS[sq] & enemy_zone)
            if pt == ROOK:
                file_mask = chess.BB_FILES[chess.square_file(sq)]
                if not our_pawns & file_mask:
                    bonus = ROOK_HALF_OPEN_FILE if their_pawns & file_mask else ROOK_OPEN_FILE
                    rook_mg += bonus[0]
                    rook_eg += bonus[1]

    # --- pawn structure and passed pawns
    struct_mg = struct_eg = pass_mg = pass_eg = 0
    for f in range(8):
        on_file = chess.popcount(our_pawns & chess.BB_FILES[f])
        if on_file > 1:
            struct_mg += DOUBLED_PAWN[0] * (on_file - 1)
            struct_eg += DOUBLED_PAWN[1] * (on_file - 1)
        if on_file and not our_pawns & _ADJACENT_FILES[f]:
            struct_mg += ISOLATED_PAWN[0] * on_file
            struct_eg += ISOLATED_PAWN[1] * on_file
    passed_masks = _PASSED_MASKS[color]
    for sq in chess.scan_forward(our_pawns):
        if not their_pawns & passed_masks[sq]:
            rel_rank = chess.square_rank(sq) if color == chess.WHITE else 7 - chess.square_rank(sq)
            pass_mg += PASSED_PAWN_MG[rel_rank]
            pass_eg += PASSED_PAWN_EG[rel_rank]

    # --- king safety (middlegame only; in the endgame the king should be active)
    king_mg = 0
    king_sq = board.king(color)
    if king_sq is not None:
        k_file, k_rank = chess.square_file(king_sq), chess.square_rank(king_sq)
        rel_rank = k_rank if color == chess.WHITE else 7 - k_rank
        step = 1 if color == chess.WHITE else -1
        files = range(max(0, k_file - 1), min(7, k_file + 1) + 1)
        if rel_rank <= 1:  # king still near its own back rank: check the pawn shield
            for f in files:
                if our_pawns & chess.BB_SQUARES[chess.square(f, k_rank + step)]:
                    continue
                if our_pawns & chess.BB_SQUARES[chess.square(f, k_rank + 2 * step)]:
                    king_mg += SHIELD_PAWN_ADVANCED
                else:
                    king_mg += SHIELD_PAWN_MISSING
        for f in files:
            if not our_pawns & chess.BB_FILES[f]:
                king_mg += KING_FILE_HALF_OPEN
                if not their_pawns & chess.BB_FILES[f]:
                    king_mg += KING_FILE_OPEN
        # (attacks on this king are added by evaluate_breakdown, see _side_terms doc)

    pair = BISHOP_PAIR if chess.popcount(board.pieces_mask(BISHOP, color)) >= 2 else (0, 0)
    tempo = TEMPO if board.turn == color else (0, 0)

    # Same order as TERMS (a plain list is faster than a dict in the search's hot path).
    return [
        (mat_mg, mat_eg),
        (pst_mg, pst_eg),
        (struct_mg, struct_eg),
        (pass_mg, pass_eg),
        (mob_mg, mob_eg),
        (king_mg, 0),
        pair,
        (rook_mg, rook_eg),
        tempo,
    ], pressure


_KING_SAFETY = TERMS.index("king_safety")


def _all_terms(board: chess.Board):
    """(phase, white terms, black terms), including the cross-wise king attack penalty."""
    phase = game_phase(board)
    white, white_pressure = _side_terms(board, chess.WHITE)
    black, black_pressure = _side_terms(board, chess.BLACK)
    # Each side's king safety loses points for the attacks the *other* side makes on it.
    w_mg, w_eg = white[_KING_SAFETY]
    white[_KING_SAFETY] = (
        w_mg - _king_attack_penalty(black_pressure, bool(board.pieces_mask(QUEEN, chess.BLACK))),
        w_eg,
    )
    b_mg, b_eg = black[_KING_SAFETY]
    black[_KING_SAFETY] = (
        b_mg - _king_attack_penalty(white_pressure, bool(board.pieces_mask(QUEEN, chess.WHITE))),
        b_eg,
    )
    return phase, white, black


def _taper(mg: int, eg: int, phase: int) -> int:
    return (mg * phase + eg * (MAX_PHASE - phase)) // MAX_PHASE


# ---------------------------------------------------------------- public API


@dataclass(frozen=True)
class TermScore:
    """One evaluation term: White's and Black's share in centipawns."""

    white: int
    black: int

    @property
    def net(self) -> int:
        """White minus Black: positive = good for White."""
        return self.white - self.black


@dataclass(frozen=True)
class EvalBreakdown:
    """The evaluation split into terms. All values are from White's point of view."""

    phase: int  # 24 = middlegame ... 0 = endgame
    terms: dict[str, TermScore]

    @property
    def total(self) -> int:
        """Total score in centipawns, White's point of view."""
        return sum(t.net for t in self.terms.values())

    def for_side(self, color: chess.Color) -> int:
        return self.total if color == chess.WHITE else -self.total

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "total": self.total,
            "terms": {
                name: {"label": TERM_LABELS[name], "white": t.white,
                       "black": t.black, "net": t.net}
                for name, t in self.terms.items()
            },
        }


def evaluate_breakdown(board: chess.Board) -> EvalBreakdown:
    phase, white, black = _all_terms(board)
    return EvalBreakdown(
        phase=phase,
        terms={
            name: TermScore(_taper(*white[i], phase), _taper(*black[i], phase))
            for i, name in enumerate(TERMS)
        },
    )


_EVAL_CACHE: dict = {}
_EVAL_CACHE_MAX = 500_000


def evaluate(board: chess.Board) -> int:
    """Score in centipawns from the **side to move's** point of view (negamax style).

    Exactly ``evaluate_breakdown(board).for_side(board.turn)``, but without building
    the breakdown objects, and cached: the search meets the same positions often.
    Checkmate / stalemate / draws are handled by the search, not here.
    """
    key = board.position_key()  # pieces + side to move + castling + en passant
    cached = _EVAL_CACHE.get(key)
    if cached is not None:
        return cached
    phase, white, black = _all_terms(board)
    inv = MAX_PHASE - phase
    total = 0
    for (w_mg, w_eg), (b_mg, b_eg) in zip(white, black):
        total += ((w_mg * phase + w_eg * inv) // MAX_PHASE
                  - (b_mg * phase + b_eg * inv) // MAX_PHASE)
    score = total if board.turn == chess.WHITE else -total
    if len(_EVAL_CACHE) >= _EVAL_CACHE_MAX:
        _EVAL_CACHE.clear()
    _EVAL_CACHE[key] = score
    return score


def compare(before: EvalBreakdown, after: EvalBreakdown) -> dict[str, int]:
    """How much each term changed (White's point of view), e.g. after a move.
    Used to explain moves: {"king_safety": +35, "material": 0, ...}."""
    return {name: after.terms[name].net - before.terms[name].net for name in TERMS}
