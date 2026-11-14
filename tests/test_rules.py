"""Tests for our own chess rules module (chess_ai.chess).

Move generation itself is proven by the perft tests (test_perft.py). These cover
everything else: FEN, SAN, UCI, PGN, special moves, game-end rules and helpers.
"""

import random

import pytest

from chess_ai import chess
from chess_ai.chess import pgn

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
E5_PAWN_BLACK_TO_MOVE = "rnbqkbnr/pppppppp/8/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2"


# --------------------------------------------------------------- squares & bitboards


def test_square_helpers():
    assert chess.square_name(0) == "a1" and chess.square_name(63) == "h8"
    assert chess.parse_square("e4") == chess.square(4, 3) == 28
    assert chess.square_file(28) == 4 and chess.square_rank(28) == 3
    assert list(chess.scan_forward(0b1010)) == [1, 3]
    assert chess.popcount(chess.BB_RANK_1) == 8
    assert chess.flip_vertical(chess.BB_RANK_1) == chess.BB_RANK_8


def test_slider_attacks_stop_at_blockers():
    occ = chess.BB_SQUARES[chess.parse_square("e6")] | chess.BB_SQUARES[chess.parse_square("c4")]
    attacks = chess.rook_attacks(chess.parse_square("e4"), occ)
    names = {chess.square_name(s) for s in chess.scan_forward(attacks)}
    assert {"e5", "e6", "d4", "c4", "e1", "h4"} <= names
    assert "e7" not in names and "b4" not in names
    assert chess.BETWEEN[chess.parse_square("a1")][chess.parse_square("d4")] == (
        chess.BB_SQUARES[chess.parse_square("b2")] | chess.BB_SQUARES[chess.parse_square("c3")])


# --------------------------------------------------------------- FEN


@pytest.mark.parametrize("fen", [
    chess.STARTING_FEN, KIWIPETE,
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",  # en passant possible
])
def test_fen_round_trip(fen):
    assert chess.Board(fen).fen() == fen


@pytest.mark.parametrize("bad", ["", "nonsense", "8/8/8 w - - 0 1",
                                 "rnbqkbnr/pppppppp/9/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                                 "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1"])
def test_bad_fen_rejected(bad):
    with pytest.raises(ValueError):
        chess.Board(bad)


def test_en_passant_shown_only_when_playable():
    b = chess.Board()
    b.push_san("e4")  # no black pawn can capture on e3
    assert b.fen().split()[3] == "-"
    b = chess.Board(E5_PAWN_BLACK_TO_MOVE)
    b.push_san("d5")  # the e5 pawn can take d6 en passant
    assert b.fen().split()[3] == "d6"


def test_castling_rights_cleaned_and_updated():
    # rights for missing rooks are dropped
    assert chess.Board("4k3/8/8/8/8/8/8/4K2R w KQ - 0 1").castling_fen() == "K"
    b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    b.push_san("Rxa8+")  # rook captures rook: both a-file rights are gone
    assert b.castling_fen() == "Kk"
    b.push_san("Ke7")
    assert b.castling_fen() == "K"


def test_status_and_validity():
    assert chess.Board().is_valid()
    assert not chess.Board("8/8/8/8/8/8/8/8 w - - 0 1").is_valid()  # no kings
    in_check_not_to_move = chess.Board("4k3/8/8/8/8/8/8/4RK2 w - - 0 1")
    assert "the side not to move is in check" in in_check_not_to_move.status()


# --------------------------------------------------------------- moves


def test_uci_parsing():
    assert chess.Move.from_uci("e7e8q") == chess.Move(52, 60, chess.QUEEN)
    assert chess.Move.from_uci("e7e8q").uci() == "e7e8q"
    assert not chess.Move.null() and chess.Move.null().uci() == "0000"
    for bad in ["e2", "e2e9", "e2e4k", "e2e2", "zz11"]:
        with pytest.raises(ValueError):
            chess.Move.from_uci(bad)


def test_special_moves():
    b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    b.push_san("O-O")
    assert b.piece_at(chess.parse_square("f1")).symbol() == "R"
    assert b.piece_at(chess.parse_square("g1")).symbol() == "K"
    b.push_san("O-O-O")
    assert b.piece_at(chess.parse_square("d8")).symbol() == "r"
    b.pop()
    b.pop()
    assert b.fen() == "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"

    b = chess.Board(E5_PAWN_BLACK_TO_MOVE)
    b.push_san("d5")
    move = b.parse_san("exd6")
    assert b.is_en_passant(move) and b.is_capture(move)
    b.push(move)
    assert b.piece_at(chess.parse_square("d5")) is None  # captured pawn removed

    b = chess.Board("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    b.push_san("a8=N")
    assert b.piece_at(chess.parse_square("a8")).symbol() == "N"


def test_cannot_castle_through_check_or_out_of_check():
    through = chess.Board("4kr2/8/8/8/8/8/8/4K2R w K - 0 1")  # f1 attacked
    assert chess.Move.from_uci("e1g1") not in through.legal_moves
    in_check = chess.Board("4r1k1/8/8/8/8/8/8/R3K2R w KQ - 0 1")  # rook e8 checks
    assert chess.Move.from_uci("e1g1") not in in_check.legal_moves
    assert chess.Move.from_uci("e1c1") not in in_check.legal_moves


def test_pinned_piece_and_en_passant_pin():
    pinned = chess.Board("4k3/8/8/8/4r3/8/4N3/4K3 w - - 0 1")  # knight pinned on e-file
    assert not any(m.from_square == chess.parse_square("e2") for m in pinned.legal_moves)
    # en passant would expose the king along the 5th rank: illegal
    ep_pin = chess.Board("8/8/8/K2pP2r/8/8/8/7k w - d6 0 1")
    assert chess.Move.from_uci("e5d6") not in ep_pin.legal_moves


# --------------------------------------------------------------- SAN


@pytest.mark.parametrize(("fen", "uci", "san"), [
    (chess.STARTING_FEN, "g1f3", "Nf3"),
    ("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "e1g1", "O-O"),
    ("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "e1c1", "O-O-O"),
    ("4k3/8/8/8/8/8/4K3/R6R w - - 0 1", "a1d1", "Rad1"),  # file disambiguation
    ("4k3/8/8/8/R7/8/8/R3K3 w - - 0 1", "a1a2", "R1a2"),  # rank disambiguation
    ("4k3/8/8/8/8/8/1P6/K7 w - - 0 1", "b2b4", "b4"),
    ("8/P6k/8/8/8/8/8/K7 w - - 0 1", "a7a8q", "a8=Q"),
    ("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1a8", "Ra8#"),
    ("4k3/8/8/8/8/8/8/R3K3 w Q - 0 1", "a1a8", "Ra8+"),
])
def test_san(fen, uci, san):
    b = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    assert b.san(move) == san
    assert b.parse_san(san) == move


def test_queen_square_disambiguation():
    b = chess.Board("4k3/8/8/8/Q1Q5/8/Q7/4K3 w - - 0 1")  # queens a4, c4, a2 all reach b3
    assert b.san(chess.Move.from_uci("a4b3")) == "Qa4b3"


def test_san_round_trip_in_random_games():
    rng = random.Random(42)
    for _ in range(40):
        b = chess.Board()
        for _ in range(rng.randint(10, 120)):
            moves = list(b.legal_moves)
            if not moves:
                break
            for m in moves:
                assert b.parse_san(b.san(m)) == m
            b.push(rng.choice(moves))
        assert chess.Board(b.fen()).fen() == b.fen()


def test_generate_legal_captures_in_random_games():
    """Captures (incl. en passant) must be exactly the legal moves that capture."""
    rng = random.Random(3)
    for fen in [chess.STARTING_FEN, KIWIPETE, "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"]:
        for _ in range(25):
            b = chess.Board(fen)
            for _ in range(rng.randint(5, 80)):
                moves = list(b.legal_moves)
                if not moves:
                    break
                expected = sorted(m.uci() for m in moves if b.is_capture(m))
                assert sorted(m.uci() for m in b.generate_legal_captures()) == expected
                b.push(rng.choice(moves))


def test_piece_moving_to_en_passant_square_is_not_a_capture():
    # Black just played d7-d5; the knight on b5 can go to the (empty) en passant square d6
    b = chess.Board("4k3/8/8/1N1pP3/8/8/8/4K3 w - d6 0 1")
    captures = {m.uci() for m in b.generate_legal_captures()}
    assert "e5d6" in captures and "b5d6" not in captures


def test_variation_san():
    b = chess.Board()
    line = [chess.Move.from_uci(u) for u in ["e2e4", "e7e5", "g1f3"]]
    assert b.variation_san(line) == "1. e4 e5 2. Nf3"
    b.push(line[0])
    assert b.variation_san(line[1:]) == "1... e5 2. Nf3"


# --------------------------------------------------------------- game end


def test_checkmate_stalemate_and_outcome():
    mate = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert mate.is_checkmate() and mate.outcome().winner == chess.BLACK
    assert mate.outcome().result() == "0-1"
    stale = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert stale.is_stalemate()
    assert stale.outcome().termination == chess.Termination.STALEMATE
    assert chess.Board().outcome() is None and not chess.Board().is_game_over()


@pytest.mark.parametrize(("fen", "insufficient"), [
    ("8/8/8/8/8/8/8/K6k w - - 0 1", True),  # K v K
    ("8/8/8/8/8/8/8/KN5k w - - 0 1", True),  # K+N v K
    ("8/8/8/8/8/8/8/KB5k w - - 0 1", True),  # K+B v K
    ("8/8/8/8/8/8/8/KR5k w - - 0 1", False),  # K+R v K
    ("8/8/8/8/8/8/P7/K6k w - - 0 1", False),  # pawn can promote
    ("8/8/8/8/8/8/8/KBB4k w - - 0 1", False),  # bishops on both colours
])
def test_insufficient_material(fen, insufficient):
    assert chess.Board(fen).is_insufficient_material() == insufficient


def test_repetition_and_fifty_moves():
    b = chess.Board()
    for san in ["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8"]:
        b.push_san(san)
    assert b.is_repetition(3) and not b.is_repetition(4)
    assert b.outcome(claim_draw=True).termination == chess.Termination.THREEFOLD_REPETITION
    assert b.outcome() is None  # threefold must be claimed; it is not automatic
    fifty = chess.Board("8/8/8/4k3/8/8/8/R3K3 w - - 100 80")
    assert fifty.outcome(claim_draw=True).termination == chess.Termination.FIFTY_MOVES


def test_mirror():
    b = chess.Board(KIWIPETE)
    m = b.mirror()
    assert m.turn == chess.BLACK
    assert m.mirror().fen() == b.fen()
    assert m.legal_moves.count() == b.legal_moves.count()


def test_push_pop_restores_everything():
    rng = random.Random(7)
    b = chess.Board(KIWIPETE)
    fens = [b.fen()]
    for _ in range(30):
        moves = list(b.legal_moves)
        if not moves:
            break
        b.push(rng.choice(moves))
        fens.append(b.fen())
    while b.move_stack:
        fens.pop()
        b.pop()
        assert b.fen() == fens[-1]


def test_unicode_picture():
    text = chess.Board().unicode(borders=True)
    assert text.splitlines()[0].startswith("8 |")
    assert "♔" in text and "♚" in text
    assert str(chess.Board()).splitlines()[-1] == "R N B Q K B N R"


# --------------------------------------------------------------- PGN


def test_pgn_write_and_read_back():
    b = chess.Board()
    moves = [b.push_san(s) for s in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O"]]
    text = pgn.write_pgn({"Event": "Test", "White": "A", "Black": "B"}, moves, result="*")
    assert '[White "A"]' in text and "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. O-O *" in text
    parsed = pgn.read_pgn(text)
    assert parsed.moves == moves and parsed.headers["Event"] == "Test"


def test_pgn_skips_comments_variations_and_nags():
    text = """[Event "x"]

1. e4 {best by test} e5 (1... c5 2. Nf3) 2. Nf3 $1 Nc6 ; a comment
3. Bb5 1-0"""
    parsed = pgn.read_pgn(text)
    assert [m.uci() for m in parsed.moves] == ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]


def test_pgn_custom_start_and_errors():
    start = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    b = chess.Board(start)
    moves = [b.push_san("O-O"), b.push_san("O-O-O")]
    text = pgn.write_pgn({}, moves, start, "1/2-1/2")
    assert '[FEN "' + start + '"]' in text
    assert pgn.read_pgn(text).end_board().fen() == b.fen()
    with pytest.raises(ValueError):
        pgn.read_pgn("")
    with pytest.raises(ValueError):
        pgn.read_pgn("1. e4 e5 2. Ke3 Kxe9")
