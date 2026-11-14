"""Tests for the game layer (chess_ai.game)."""

import chess
import pytest

from chess_ai.game import BLACK, WHITE, Game, IllegalMoveError


def play(game: Game, *moves: str) -> None:
    for m in moves:
        game.make_move(m)


# --------------------------------------------------------------- basics


def test_new_game_state():
    g = Game()
    assert g.fen == chess.STARTING_FEN
    assert g.turn == WHITE
    assert g.history == []
    assert not g.is_over
    assert len(g.legal_moves()) == 20


def test_moves_in_uci_and_san():
    g = Game()
    rec = g.make_move("e2e4")
    assert (rec.san, rec.uci, rec.color, rec.ply, rec.move_number) == ("e4", "e2e4", WHITE, 1, 1)
    rec = g.make_move(" Nf6 ")
    assert (rec.san, rec.uci, rec.color, rec.ply, rec.move_number) == ("Nf6", "g8f6", BLACK, 2, 1)
    assert rec.piece == "N" and rec.from_square == "g8" and rec.to_square == "f6"
    assert g.turn == WHITE


@pytest.mark.parametrize("bad", ["e2e5", "Ke2", "hello", "", "e7e5"])
def test_illegal_moves_rejected(bad):
    g = Game()
    with pytest.raises(IllegalMoveError):
        g.make_move(bad)
    assert g.history == []  # nothing changed


def test_invalid_fen_rejected():
    with pytest.raises(ValueError):
        Game("not a fen")
    with pytest.raises(ValueError):  # parses, but no kings: illegal position
        Game("8/8/8/8/8/8/8/8 w - - 0 1")


# --------------------------------------------------------------- move records


def test_capture_record_and_material():
    g = Game()
    play(g, "e4", "d5", "exd5")
    rec = g.last_move
    assert rec.captured == "P" and rec.san == "exd5"
    assert g.captured_pieces() == {WHITE: ["P"], BLACK: []}
    assert g.material_balance() == 1


def test_en_passant_record():
    g = Game()
    play(g, "e4", "a6", "e5", "d5", "exd6")
    rec = g.last_move
    assert rec.is_en_passant and rec.captured == "P" and rec.uci == "e5d6"


def test_castling_record():
    g = Game("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    rec = g.make_move("O-O")
    assert rec.castling == "kingside" and rec.captured is None and rec.uci == "e1g1"
    rec = g.make_move("O-O-O")
    assert rec.castling == "queenside" and rec.color == BLACK


def test_promotion():
    g = Game("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert g.needs_promotion("a7", "a8")
    assert not g.needs_promotion("a1", "a2")
    assert g.legal_moves_by_square()["a7"] == ["a8"]  # 4 promotion moves -> one target
    rec = g.make_move("a7a8q")
    assert rec.promotion == "Q" and rec.san == "a8=Q"
    assert g.material_balance() == 9


def test_check_flag():
    g = Game()
    play(g, "e4", "f6", "d4", "g5")
    rec = g.make_move("Qh5")
    assert rec.is_check and rec.is_checkmate and rec.san == "Qh5#"


# --------------------------------------------------------------- game endings


def test_checkmate_fools_mate():
    g = Game()
    play(g, "f3", "e5", "g4", "Qh4")
    s = g.status()
    assert (s.is_over, s.reason, s.winner, s.result) == (True, "checkmate", BLACK, "0-1")
    with pytest.raises(IllegalMoveError):
        g.make_move("e4")


def test_stalemate():
    g = Game("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    s = g.status()
    assert (s.is_over, s.reason, s.winner, s.result) == (True, "stalemate", None, "1/2-1/2")


def test_insufficient_material():
    assert Game("8/8/8/8/8/8/8/K6k w - - 0 1").status().reason == "insufficient_material"


def test_threefold_repetition():
    g = Game()
    play(g, "Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1")
    assert not g.is_over
    g.make_move("Ng8")  # starting position now seen for the third time
    assert g.status().reason == "threefold_repetition"


def test_fifty_move_rule():
    g = Game("8/8/8/4k3/8/8/8/R3K3 w - - 99 80")
    assert not g.is_over
    g.make_move("Ra2")  # 100th half-move without capture or pawn move
    assert g.status().reason == "fifty_moves"


def test_resign_and_draw_agreement():
    g = Game()
    s = g.resign(WHITE)
    assert (s.reason, s.winner, s.result) == ("resignation", BLACK, "0-1")
    with pytest.raises(IllegalMoveError):
        g.agree_draw()

    g = Game()
    g.make_move("e4")
    s = g.agree_draw()
    assert (s.reason, s.winner, s.result) == ("draw_agreed", None, "1/2-1/2")


# --------------------------------------------------------------- undo


def test_undo_human_and_ai_move():
    g = Game()
    play(g, "e4", "e5", "Nf3")
    undone = g.undo(2)
    assert [r.san for r in undone] == ["Nf3", "e5"]
    assert [r.san for r in g.history] == ["e4"]
    assert g.turn == BLACK


def test_undo_errors_and_cancels_resignation():
    g = Game()
    with pytest.raises(IllegalMoveError):
        g.undo()
    g.make_move("e4")
    g.resign(BLACK)
    assert g.is_over
    g.undo()
    assert not g.is_over and g.fen == chess.STARTING_FEN


# --------------------------------------------------------------- FEN / PGN


def test_fen_round_trip():
    fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    assert Game.from_fen(fen).fen == fen


def test_pgn_round_trip():
    g = Game()
    play(g, "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Bxc6", "dxc6", "O-O")
    pgn = g.to_pgn(white="Player", black="AI")
    assert '[White "Player"]' in pgn and '[Result "*"]' in pgn
    loaded = Game.from_pgn(pgn)
    assert loaded.fen == g.fen
    assert [r.san for r in loaded.history] == [r.san for r in g.history]


def test_pgn_from_custom_position_and_result():
    g = Game("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    play(g, "O-O")
    g.resign(BLACK)
    pgn = g.to_pgn()
    assert '[Result "1-0"]' in pgn and '[Termination "resignation"]' in pgn
    loaded = Game.from_pgn(pgn)
    assert loaded.start_fen == g.start_fen and loaded.fen == g.fen


def test_bad_pgn_rejected():
    with pytest.raises(ValueError):
        Game.from_pgn("")
    with pytest.raises(ValueError):
        Game.from_pgn("1. e4 e5 2. Ke3 Kxe9")


def test_to_dict_has_everything_the_ui_needs():
    g = Game()
    play(g, "e4")
    d = g.to_dict()
    assert set(d) == {"fen", "start_fen", "turn", "is_check", "status", "history",
                      "legal_moves", "captured", "material_balance"}
    assert d["history"][0]["san"] == "e4"
    assert "e5" in d["legal_moves"]["e7"]
