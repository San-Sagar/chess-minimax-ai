"""Tests for Phase 6: opening book, opening names, tablebases and the Engine wrapper."""

import struct

import chess
import chess.polyglot
import pytest

from chess_ai.engine.book import OpeningBook
from chess_ai.engine.engine import Engine
from chess_ai.engine.openings import BOOK_LINES, OPENING_NAMES
from chess_ai.engine.search import TB_WIN, Searcher, format_score
from chess_ai.engine.tablebase import DEFAULT_DIR, Tablebase

TB = Tablebase(DEFAULT_DIR)
needs_tb = pytest.mark.skipif(not TB.available, reason="Syzygy files not in data/syzygy")


def play(*sans: str) -> chess.Board:
    b = chess.Board()
    for s in sans:
        b.push_san(s)
    return b


# --------------------------------------------------------------- curated data


@pytest.mark.parametrize("line", [b[2] for b in BOOK_LINES] + [n[2] for n in OPENING_NAMES])
def test_every_curated_line_is_legal(line):
    board = chess.Board()
    for san in line.split():
        board.push_san(san)  # raises if illegal


def test_book_lines_are_unique():
    lines = [b[2] for b in BOOK_LINES]
    assert len(lines) == len(set(lines))


# --------------------------------------------------------------- book


def test_book_from_start():
    book = OpeningBook(polyglot_path=None, seed=1)
    opts, source = book.options(chess.Board())
    assert source == "curated"
    assert {o.san for o in opts} >= {"e4", "d4", "c4", "Nf3"}
    assert opts[0].san == "e4"  # most popular
    assert abs(sum(o.share for o in opts) - 1) < 1e-9
    probe = book.probe(chess.Board())
    assert probe.move in chess.Board().legal_moves
    assert probe.opening is not None


def test_book_best_and_seeded_randomness():
    a = OpeningBook(polyglot_path=None, seed=7)
    b = OpeningBook(polyglot_path=None, seed=7)
    moves_a = [a.probe(chess.Board()).move for _ in range(10)]
    moves_b = [b.probe(chess.Board()).move for _ in range(10)]
    assert moves_a == moves_b
    assert len(set(moves_a)) > 1  # variety
    assert a.probe(chess.Board(), best=True).move == chess.Move.from_uci("e2e4")


def test_book_follows_theory_and_stops():
    book = OpeningBook(polyglot_path=None)
    board = play("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3")
    assert book.probe(board, best=True).move.uci() == "a7a6"  # the Najdorf
    out_of_book = play("a3", "h6", "h3", "a6")
    assert book.probe(out_of_book) is None


def test_book_respects_max_ply():
    book = OpeningBook(polyglot_path=None, max_ply=2)
    assert book.probe(play("e4", "e5")) is None


def test_opening_names_and_transpositions():
    book = OpeningBook(polyglot_path=None)
    najdorf = play("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6")
    assert book.opening_name(najdorf).name == "Sicilian Defense: Najdorf"
    # Nimzo-Indian reached by a different move order
    nimzo = play("c4", "e6", "d4", "Nf6", "Nc3", "Bb4")
    assert book.opening_name(nimzo).name == "Nimzo-Indian Defense"
    # leaving theory keeps the deepest name reached
    later = play("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "h3", "h6")
    assert book.opening_name(later).name == "Ruy Lopez: Morphy Defense"
    assert book.opening_name(chess.Board()) is None


def _polyglot_move(move: chess.Move) -> int:
    return (chess.square_file(move.to_square) | chess.square_rank(move.to_square) << 3
            | chess.square_file(move.from_square) << 6
            | chess.square_rank(move.from_square) << 9)


def test_external_polyglot_book_is_used(tmp_path):
    """Write a one-entry Polyglot book (1.b3 from the start) and check it wins."""
    board = chess.Board()
    entry = struct.pack(">QHHI", chess.polyglot.zobrist_hash(board),
                        _polyglot_move(chess.Move.from_uci("b2b3")), 10, 0)
    path = tmp_path / "book.bin"
    path.write_bytes(entry)
    book = OpeningBook(polyglot_path=path)
    assert book.has_polyglot
    probe = book.probe(board)
    assert probe.source == "polyglot" and probe.move.uci() == "b2b3"
    # positions not in the Polyglot file fall back to the curated book
    assert book.probe(play("e4"), best=True).source == "curated"
    book.close()


# --------------------------------------------------------------- tablebase


def test_missing_tablebase_is_harmless(tmp_path):
    tb = Tablebase(tmp_path)
    assert not tb.available and tb.max_pieces == 0
    board = chess.Board("8/8/8/8/8/8/1Q6/K6k w - - 0 1")
    assert tb.probe_wdl(board) is None and tb.best_move(board) is None
    assert Searcher(tablebase=tb).tablebase is None


def test_tablebase_score_formatting():
    assert format_score(TB_WIN - 5) == "TB win"
    assert format_score(-TB_WIN + 5) == "TB loss"


@needs_tb
def test_tablebase_results():
    assert TB.probe_wdl(chess.Board("8/8/8/8/8/8/1Q6/K6k w - - 0 1")) == 2  # KQ v K
    assert TB.probe_wdl(chess.Board("8/8/8/8/8/8/1Q6/K6k b - - 0 1")) == -2
    assert TB.probe_wdl(chess.Board("8/8/8/4k3/8/8/4K3/8 w - - 0 1")) == 0  # K v K
    assert TB.probe_wdl(chess.Board()) is None  # 32 pieces: not covered


@needs_tb
def test_tablebase_best_move_wins_krk():
    """Follow the tablebase in K+R v K and check it actually mates."""
    board = chess.Board("8/8/8/4k3/8/8/8/R3K3 w - - 0 1")
    for _ in range(60):
        if board.is_game_over():
            break
        if board.turn == chess.WHITE:
            board.push(TB.best_move(board).move)
        else:
            board.push(TB.best_move(board).move)  # defender resists as long as possible
    assert board.is_checkmate()


@needs_tb
def test_search_uses_tablebase_after_capture():
    # White can take the last black piece (the rook), entering a won KQvK.
    board = chess.Board("4k3/8/8/8/8/8/3r4/3QK3 w - - 0 1")
    r = Searcher(tablebase=TB).search(board, max_depth=3)
    assert r.best_move.uci() == "d1d2" or r.best_move.uci() == "e1d2"
    assert r.stats.tb_hits > 0 and format_score(r.score) == "TB win"


# --------------------------------------------------------------- engine


def test_engine_uses_book_then_search():
    engine = Engine(seed=3)
    reply = engine.choose_move(chess.Board())
    assert reply.source == "book" and reply.score is None and reply.opening is not None
    middlegame = chess.Board("r2q1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2Q1RK1 w - - 0 10")
    reply = engine.choose_move(middlegame, time_limit=1.0, analysis_time=0.5)
    assert reply.source == "search" and reply.analysis is not None
    assert reply.move in middlegame.legal_moves
    d = reply.to_dict()
    assert d["source"] == "search" and d["analysis"]["best"]["san"] == reply.san


def test_engine_without_book_searches_from_start():
    engine = Engine(use_book=False, use_tablebase=False)
    reply = engine.choose_move(chess.Board(), max_depth=3, analyze=False)
    assert reply.source == "search" and reply.analysis is None


def test_engine_rejects_finished_game():
    with pytest.raises(ValueError):
        Engine().choose_move(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"))


def test_engine_info():
    info = Engine().info()
    assert info["book_positions"] > 300
    assert info["tablebase"] == TB.available


@needs_tb
def test_engine_plays_tablebase_moves():
    engine = Engine()
    reply = engine.choose_move(chess.Board("8/8/8/4k3/8/8/8/R3K3 w - - 0 1"))
    assert reply.source == "tablebase" and reply.score_text == "TB win"
