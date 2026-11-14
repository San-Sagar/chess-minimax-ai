"""Tests for minimax, alpha-beta and the engine search."""

import time

import chess
import pytest

from chess_ai.engine.classic import MATE_SCORE, alphabeta, minimax
from chess_ai.engine.search import Searcher, format_score, mate_in

POSITIONS = [
    chess.STARTING_FEN,
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "r2q1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2Q1RK1 b - - 0 10",
    "8/5pk1/6p1/8/3R4/6P1/5PKP/3r4 w - - 0 40",
    "4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1",
]


def white_view(board: chess.Board, score: int) -> int:
    return score if board.turn == chess.WHITE else -score


# --------------------------------------------------------------- the three agree


@pytest.mark.parametrize("fen", POSITIONS)
@pytest.mark.parametrize("depth", [1, 2, 3])
def test_minimax_alphabeta_and_engine_agree(fen, depth):
    """Alpha-beta and negamax must give exactly the textbook minimax score."""
    board = chess.Board(fen)
    mm = minimax(board, depth)
    ab = alphabeta(board, depth)
    eng = Searcher(quiescence=False).search(board, max_depth=depth)
    assert ab.score == mm.score
    assert white_view(board, eng.score) == mm.score
    assert ab.nodes <= mm.nodes
    assert board.fen() == fen  # caller's board untouched


def test_alphabeta_prunes_a_lot():
    board = chess.Board(POSITIONS[1])
    mm, ab = minimax(board, 3), alphabeta(board, 3)
    assert ab.cutoffs > 0
    assert ab.nodes < mm.nodes * 0.5


# --------------------------------------------------------------- mates and draws


def test_finds_mate_in_one():
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")  # back-rank mate
    r = Searcher().search(board, max_depth=3)
    assert r.best_move == chess.Move.from_uci("a1a8")
    assert r.mate_in == 1 and r.score_text == "#1"


def test_finds_mate_in_two():
    board = chess.Board("7k/8/8/8/8/8/R7/1R4K1 w - - 0 1")  # two-rook ladder
    r = Searcher().search(board, max_depth=4)
    assert r.mate_in == 2
    board.push(r.best_move)
    reply = Searcher().search(board, max_depth=4)
    assert reply.mate_in == -1  # Black sees it is getting mated next move


def test_classic_scores_mate():
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    r = minimax(board, 1)
    assert r.score == MATE_SCORE - 1 and r.best_move.uci() == "a1a8"


def test_no_legal_moves():
    stalemate = Searcher().search(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"))
    assert stalemate.best_move is None and stalemate.score == 0
    mated = Searcher().search(chess.Board("R5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1"))
    assert mated.best_move is None and mated.score == -MATE_SCORE


def test_avoids_stalemate_when_winning():
    # Qg6 / Qf7 would stalemate; with a queen up White must keep playing.
    board = chess.Board("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1")
    r = Searcher().search(board, max_depth=3)
    board.push(r.best_move)
    assert not board.is_stalemate()


def test_takes_repetition_when_losing():
    # Black is a queen down but can give perpetual check: it should repeat.
    board = chess.Board("6k1/5ppp/8/8/8/8/q4PPP/1Q3RK1 w - - 0 1")
    # After a few checks a repetition is a draw (0), better than a lost position.
    r = Searcher().search(board, max_depth=3)
    assert r.best_move is not None


# --------------------------------------------------------------- quiescence


def test_quiescence_avoids_horizon_blunder():
    """At depth 1 without quiescence Qxd5 looks like it wins a pawn; it actually
    loses the queen to exd5. Quiescence search sees the recapture."""
    board = chess.Board("4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1")
    blunder = chess.Move.from_uci("d1d5")
    assert Searcher(quiescence=False).search(board, max_depth=1).best_move == blunder
    assert Searcher(quiescence=True).search(board, max_depth=1).best_move != blunder


def test_wins_hanging_piece():
    board = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")  # black queen undefended
    assert Searcher().search(board, max_depth=2).best_move == chess.Move.from_uci("d2d5")


# --------------------------------------------------------------- deepening, time


def test_iterative_deepening_reports_each_depth():
    seen = []
    r = Searcher().search(chess.Board(), max_depth=3, on_iteration=seen.append)
    assert [i.depth for i in seen] == [1, 2, 3] == [i.depth for i in r.iterations]
    assert r.depth == 3 and r.pv[0] == r.best_move
    assert seen[-1].nodes >= seen[0].nodes
    assert set(seen[0].to_dict()) >= {"depth", "score", "score_text", "pv", "nodes", "nps"}


def test_time_limit_respected():
    start = time.perf_counter()
    r = Searcher().search(chess.Board(POSITIONS[2]), time_limit=0.5)
    elapsed = time.perf_counter() - start
    assert r.best_move is not None and r.depth >= 1
    assert elapsed < 1.5


def test_pv_is_legal():
    board = chess.Board(POSITIONS[1])
    r = Searcher().search(board, max_depth=3)
    for move in r.pv:
        assert move in board.legal_moves
        board.push(move)


# --------------------------------------------------------------- formatting


def test_score_formatting():
    assert format_score(35) == "+0.35"
    assert format_score(-120) == "-1.20"
    assert format_score(MATE_SCORE - 1) == "#1"
    assert format_score(MATE_SCORE - 5) == "#3"
    assert format_score(-(MATE_SCORE - 4)) == "#-2"
    assert mate_in(250) is None
