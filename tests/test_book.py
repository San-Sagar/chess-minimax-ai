"""Tests for the opening book, opening names and the Engine wrapper."""

import pytest

from chess_ai import chess
from chess_ai.engine.book import OpeningBook
from chess_ai.engine.engine import Engine
from chess_ai.engine.openings import BOOK_LINES, OPENING_NAMES


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
    book = OpeningBook(seed=1)
    opts = book.options(chess.Board())
    assert {o.san for o in opts} >= {"e4", "d4", "c4", "Nf3"}
    assert opts[0].san == "e4"  # most popular
    assert abs(sum(o.share for o in opts) - 1) < 1e-9
    probe = book.probe(chess.Board())
    assert probe.move in chess.Board().legal_moves
    assert probe.opening is not None


def test_book_best_and_seeded_randomness():
    a, b = OpeningBook(seed=7), OpeningBook(seed=7)
    moves_a = [a.probe(chess.Board()).move for _ in range(10)]
    moves_b = [b.probe(chess.Board()).move for _ in range(10)]
    assert moves_a == moves_b
    assert len(set(moves_a)) > 1  # variety
    assert a.probe(chess.Board(), best=True).move == chess.Move.from_uci("e2e4")


def test_book_follows_theory_and_stops():
    book = OpeningBook()
    board = play("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3")
    assert book.probe(board, best=True).move.uci() == "a7a6"  # the Najdorf
    assert book.probe(play("a3", "h6", "h3", "a6")) is None


def test_book_respects_max_ply():
    assert OpeningBook(max_ply=2).probe(play("e4", "e5")) is None


def test_opening_names_and_transpositions():
    book = OpeningBook()
    najdorf = play("e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6")
    assert book.opening_name(najdorf).name == "Sicilian Defense: Najdorf"
    nimzo = play("c4", "e6", "d4", "Nf6", "Nc3", "Bb4")  # different move order
    assert book.opening_name(nimzo).name == "Nimzo-Indian Defense"
    later = play("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "h3", "h6")
    assert book.opening_name(later).name == "Ruy Lopez: Morphy Defense"
    assert book.opening_name(chess.Board()) is None


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
    reply = Engine(use_book=False).choose_move(chess.Board(), max_depth=3, analyze=False)
    assert reply.source == "search" and reply.analysis is None


def test_engine_rejects_finished_game():
    with pytest.raises(ValueError):
        Engine().choose_move(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"))


def test_engine_info():
    assert Engine().info()["book_positions"] > 300
