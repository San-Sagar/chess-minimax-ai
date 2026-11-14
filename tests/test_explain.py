"""Tests for the AI Thinking explanations (chess_ai.explain)."""

import pytest

from chess_ai import chess
from chess_ai.explain.narrative import assessment, explain_report
from chess_ai.explain.tactics import describe_move, is_hanging, move_facts
from chess_ai.server.sessions import GameSession


def facts(fen: str, san: str) -> dict[str, str]:
    board = chess.Board(fen)
    return {f.kind: f.text for f in move_facts(board, board.parse_san(san))}


# --------------------------------------------------------------- move facts


@pytest.mark.parametrize(("fen", "san", "kind", "words"), [
    ("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", "Nc7+", "fork", "rook on a8"),
    ("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1", "Rxd5", "capture", "queen on d5"),
    ("4k3/3n4/8/8/8/8/8/3BK3 w - - 0 1", "Ba4", "pin", "knight on d7 to the king"),
    ("4k3/8/8/8/3p4/4N3/8/4K3 w - - 0 1", "Nf5", "escape", "out of danger"),
    ("4r1k1/8/8/8/4B3/8/4K3/8 w - - 0 1", "Kf3", "defend", "bishop on e4"),
    (chess.STARTING_FEN, "Nf3", "develop", "knight"),
    (chess.STARTING_FEN, "e4", "centre", "centre"),
    ("4k3/8/8/3P4/8/8/8/4K3 w - - 0 1", "d6", "passed", "6th rank"),
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "O-O", "castle", "kingside"),
    ("8/P6k/8/8/8/8/8/K7 w - - 0 1", "a8=Q", "promotion", "queen"),
    ("4k3/8/8/8/8/8/8/R3K3 w - - 0 1", "Ra8+", "check", "check"),
])
def test_move_facts(fen, san, kind, words):
    found = facts(fen, san)
    assert kind in found, found
    assert words in found[kind]


def test_checkmate_is_the_only_fact():
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    out = move_facts(board, board.parse_san("Ra8#"))
    assert [f.kind for f in out] == ["checkmate"]


def test_facts_sorted_by_importance():
    board = chess.Board("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    out = move_facts(board, board.parse_san("Nc7+"))
    assert out == sorted(out, key=lambda f: -f.weight)


def test_hanging_and_describe():
    board = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")
    assert is_hanging(board, chess.parse_square("d5"))  # undefended queen
    assert not is_hanging(board, chess.parse_square("d2"))  # defended by... nothing attacks it
    assert describe_move(chess.Board(), chess.Move.from_uci("g1f3")) == "Knight g1 → f3"


def test_board_unchanged_by_fact_detection():
    board = chess.Board("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    fen = board.fen()
    move_facts(board, board.parse_san("Nc7+"))
    assert board.fen() == fen


# --------------------------------------------------------------- narrative


def test_assessment_wording():
    assert "about equal" in assessment(10, True)
    assert "slightly better" in assessment(60, True)
    assert "clearly worse" in assessment(-150, False)
    assert "winning" in assessment(900, True)
    assert "checkmate in 2" in assessment(100000 - 3, True)
    assert "no score" in assessment(None, True)


def test_search_explanation_has_every_section():
    s = GameSession(human_color="black", level="medium", seed=1,
                    fen="r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")
    s.engine.book = None  # this position is in the opening book; force a real search
    report = s.ai_move()
    e = report["explanation"]
    assert e["kind"] == "search"
    assert e["headline"].startswith(report["san"])
    for key in ("assessment", "ideas", "expected", "alternatives", "eval_changes", "search",
                "depth_story"):
        assert key in e
    assert e["ideas"] and all(i.endswith(".") for i in e["ideas"])
    assert e["expected"]["line"].startswith("4.")
    assert len(e["alternatives"]) == 2
    assert any("Plain minimax would need" in line for line in e["search"])
    assert e["depth_story"][0].startswith("Depth 1")


def test_fork_explained():
    s = GameSession(human_color="black", level="medium", seed=2,
                    fen="r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    e = s.ai_move()["explanation"]
    assert e["headline"].startswith("Nc7+")
    assert any("Forks" in i for i in e["ideas"])


def test_book_explanation():
    s = GameSession(human_color="black", level="medium", seed=3)
    report = s.ai_move()
    assert report["source"] == "book"
    e = report["explanation"]
    assert e["kind"] == "book" and "opening book" in e["assessment"].lower()
    assert e["book"]["known_moves"]


def test_refuted_tempting_captures():
    # White can grab the d5 pawn with the queen, but ...exd5 wins the queen back.
    board = chess.Board("4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1")
    s = GameSession(human_color="black", level="medium", seed=4, fen=board.fen())
    e = s.ai_move()["explanation"]
    assert not e["headline"].startswith("Qxd5")
    for r in e["refuted"]:
        assert r["refutation_san"] and "proved it scores at most" in r["why"]


def test_explanations_never_fail_in_real_games():
    """Play a few quick games: every AI move must get a real explanation."""
    for seed in range(3):
        s = GameSession(human_color="black", level="easy", seed=seed)
        for _ in range(12):
            if s.game.is_over:
                break
            report = s.ai_move()
            assert report["explanation"]["kind"] in ("search", "book"), report["explanation"]
            if s.game.is_over:
                break
            legal = s.game.legal_moves()
            s.human_move(legal[seed % len(legal)])


def test_explain_report_directly_matches_session():
    s = GameSession(human_color="black", level="easy", seed=5,
                    fen="r2q1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2Q1RK1 w - - 0 10")
    report = s.ai_move()
    board = chess.Board(report["fen_before"])
    again = explain_report(board, report)
    assert again["headline"] == report["explanation"]["headline"]
