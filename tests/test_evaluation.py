"""Tests for the evaluation function.

Most tests compare two positions that differ in one idea (e.g. passed pawn on the
4th vs the 6th rank) and check the right term moves the right way. The symmetry test
catches the classic bug of a table being read upside-down for one colour.
"""

import chess
import pytest

from chess_ai.engine.evaluation import (
    TEMPO, TERMS, compare, evaluate, evaluate_breakdown, game_phase,
)

SAMPLE_FENS = [
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
    "6k1/5ppp/8/8/8/8/1P3PPP/6K1 b - - 0 1",
]


def term(fen: str, name: str) -> int:
    """Net value (White minus Black) of one term."""
    return evaluate_breakdown(chess.Board(fen)).terms[name].net


# --------------------------------------------------------------- consistency


@pytest.mark.parametrize("fen", SAMPLE_FENS)
def test_colour_symmetry(fen):
    """Swapping colours (and side to move) must give exactly the same score."""
    board = chess.Board(fen)
    assert evaluate(board) == evaluate(board.mirror())


@pytest.mark.parametrize("fen", SAMPLE_FENS)
def test_breakdown_matches_evaluate(fen):
    board = chess.Board(fen)
    b = evaluate_breakdown(board)
    assert set(b.terms) == set(TERMS)
    assert evaluate(board) == b.for_side(board.turn)
    assert b.total == sum(t.net for t in b.terms.values())


def test_start_position_only_tempo():
    board = chess.Board()
    assert evaluate(board) == TEMPO[0]  # everything else cancels out
    board.push_san("e4")
    board.push_san("e5")
    assert evaluate(board) == TEMPO[0]  # still symmetric


def test_evaluate_is_side_to_move_relative():
    white_to_move = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    black_to_move = chess.Board("4k3/8/8/8/8/8/8/3QK3 b - - 0 1")
    assert evaluate(white_to_move) > 800
    assert evaluate(black_to_move) < -800


def test_to_dict():
    d = evaluate_breakdown(chess.Board()).to_dict()
    assert d["phase"] == 24 and d["total"] == TEMPO[0]
    assert d["terms"]["king_safety"]["label"] == "King safety"


# --------------------------------------------------------------- phase


def test_game_phase():
    assert game_phase(chess.Board()) == 24
    assert game_phase(chess.Board("4k3/pppp4/8/8/8/8/PPPP4/4K3 w - - 0 1")) == 0
    assert game_phase(chess.Board("4k3/8/8/8/8/8/8/R2QK3 w - - 0 1")) == 6


# --------------------------------------------------------------- individual terms


def test_material_extra_knight():
    assert term("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1", "material") > 250


def test_knight_prefers_centre():
    centre = term("4k3/8/8/8/4N3/8/8/4K3 w - - 0 1", "piece_squares")
    rim = term("4k3/8/8/8/8/8/8/N3K3 w - - 0 1", "piece_squares")
    assert centre > rim
    # same for a black knight (checks the table is mirrored correctly)
    centre_b = term("4k3/8/8/3n4/8/8/8/4K3 w - - 0 1", "piece_squares")
    rim_b = term("n3k3/8/8/8/8/8/8/4K3 w - - 0 1", "piece_squares")
    assert centre_b < rim_b


def test_king_centralises_in_endgame_hides_in_middlegame():
    # endgame (pawns only): central king is better
    assert (term("8/p7/8/8/4K3/8/P7/4k3 w - - 0 1", "piece_squares")
            > term("8/p7/8/8/8/8/P7/K3k3 w - - 0 1", "piece_squares"))
    # middlegame (queens and rooks on): castled king is better than a central one
    castled = "r2qk2r/pppppppp/8/8/8/8/PPPPPPPP/R2Q1RK1 w kq - 0 1"
    central = "r2qk2r/pppppppp/8/8/4K3/8/PPPPPPPP/R2Q1R2 w kq - 0 1"
    assert term(castled, "piece_squares") > term(central, "piece_squares")


def test_doubled_and_isolated_pawns_penalised():
    healthy = "4k3/8/8/8/8/8/3PP3/4K3 w - - 0 1"
    doubled = "4k3/8/8/8/8/3P4/3P4/4K3 w - - 0 1"
    isolated = "4k3/8/8/8/8/8/P3P3/4K3 w - - 0 1"
    assert term(healthy, "pawn_structure") == 0
    assert term(doubled, "pawn_structure") < 0
    assert term(isolated, "pawn_structure") < 0


def test_passed_pawn_worth_more_when_advanced():
    on_4th = term("4k3/8/8/8/3P4/8/8/4K3 w - - 0 1", "passed_pawns")
    on_6th = term("4k3/8/3P4/8/8/8/8/4K3 w - - 0 1", "passed_pawns")
    blocked = term("4k3/3p4/8/8/3P4/8/8/4K3 w - - 0 1", "passed_pawns")
    assert on_6th > on_4th > 0
    assert blocked == 0  # an enemy pawn in front: not passed


def test_mobility_open_vs_blocked_bishop():
    open_bishop = term("4k3/8/8/8/8/8/8/2B1K3 w - - 0 1", "mobility")
    blocked_bishop = term("4k3/8/8/8/8/8/1P1P4/2B1K3 w - - 0 1", "mobility")
    assert open_bishop > blocked_bishop


def test_king_safety_shield_vs_exposed():
    # queens and rooks on the board: king safety only matters in the middlegame
    shielded = "r2q2k1/5ppp/8/8/8/8/5PPP/R2Q2K1 w - - 0 1"
    exposed = "r2q2k1/5ppp/8/8/8/8/8/R2Q2K1 w - - 0 1"
    assert term(shielded, "king_safety") > term(exposed, "king_safety")


def test_king_safety_attackers():
    quiet = "r5k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"
    attacked = "6k1/5ppp/8/6NQ/8/8/5PPP/6K1 w - - 0 1"  # Q + N aiming at h7/f7
    assert term(attacked, "king_safety") > term(quiet, "king_safety")


def test_bishop_pair_and_rook_open_file():
    assert term("4k3/8/8/8/8/8/8/2B1KB2 w - - 0 1", "bishop_pair") > 0
    assert term("4k3/8/8/8/8/8/8/2N1KB2 w - - 0 1", "bishop_pair") == 0
    open_file = term("4k3/1p6/8/8/8/8/1P6/R3K3 w - - 0 1", "rook_files")
    closed = term("4k3/p7/8/8/8/8/P7/R3K3 w - - 0 1", "rook_files")
    assert open_file > closed == 0


def test_compare_shows_which_term_changed():
    before = chess.Board()
    after = chess.Board()
    after.push_san("Nf3")
    diff = compare(evaluate_breakdown(before), evaluate_breakdown(after))
    assert set(diff) == set(TERMS)
    assert diff["piece_squares"] > 0  # knight left the rim
    assert diff["material"] == 0
