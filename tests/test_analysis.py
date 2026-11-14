"""Tests for Phase 5: root-move recording, move analysis and the tree recorder."""

import json

import chess
import pytest

from chess_ai.engine.analysis import analyze_move, estimate_pruning
from chess_ai.engine.evaluation import TERMS
from chess_ai.engine.search import Searcher
from chess_ai.engine.tree import record_tree

ITALIAN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
FORK = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"  # Nc7+ wins the rook
HANGING_QUEEN = "4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1"


@pytest.fixture(scope="module")
def italian():
    board = chess.Board(ITALIAN)
    searcher = Searcher()
    result = searcher.search(board, max_depth=4)
    return board, searcher, result


# --------------------------------------------------------------- root moves


def test_every_root_move_is_recorded_once(italian):
    board, _, result = italian
    moves = [r.move for r in result.root_moves]
    assert sorted(m.uci() for m in moves) == sorted(m.uci() for m in board.legal_moves)
    assert [r.order for r in result.root_moves] == list(range(len(moves)))


def test_best_root_move_is_exact_and_others_proven_worse(italian):
    _, _, result = italian
    best = [r for r in result.root_moves if r.move == result.best_move]
    assert len(best) == 1 and best[0].bound == "exact" and best[0].score == result.score
    worse = [r for r in result.root_moves if r.bound == "upper"]
    assert worse, "alpha-beta should prove most moves worse without exact scores"
    assert all(r.score <= result.score for r in worse)
    assert any(r.refutation is not None for r in worse)
    assert sum(r.nodes for r in result.root_moves) < result.stats.nodes


def test_refutation_is_a_legal_reply(italian):
    board, _, result = italian
    for r in result.root_moves:
        if r.refutation is not None:
            b = board.copy()
            b.push(r.move)
            assert r.refutation in b.legal_moves


# --------------------------------------------------------------- analysis


def test_analysis_candidates(italian):
    board, searcher, result = italian
    a = analyze_move(board, result, searcher, top_n=3, time_limit=2.0)
    assert a.best.move == result.best_move and a.best.is_best
    assert a.candidates[0] is a.best and len(a.candidates) == 3
    assert len({c.move for c in a.candidates}) == 3
    others = [c.score for c in a.candidates[1:]]
    assert others == sorted(others, reverse=True)
    for c in a.candidates:
        assert set(c.term_changes) == set(TERMS)
        assert c.line[0] == c.move and c.line_san[0] == c.san
        b = board.copy()
        for m in c.line:  # every line is a legal sequence
            assert m in b.legal_moves
            b.push(m)


def test_analysis_json_serialisable(italian):
    board, searcher, result = italian
    d = analyze_move(board, result, searcher, top_n=2, time_limit=1.0).to_dict()
    text = json.dumps(d)
    assert '"root_moves"' in text and '"pruning"' in text
    assert d["side"] == "white" and d["best"]["is_best"]


def test_term_changes_show_material_won():
    board = chess.Board(HANGING_QUEEN)
    s = Searcher()
    r = s.search(board, max_depth=3)
    a = analyze_move(board, r, s, top_n=2, time_limit=1.0)
    assert a.best.san == "Rxd5"
    assert a.best.term_changes["material"] > 800  # from White's (the AI's) point of view


def test_term_changes_are_from_black_view_when_black_moves():
    board = chess.Board(HANGING_QUEEN).mirror()  # same idea, Black to move
    s = Searcher()
    r = s.search(board, max_depth=3)
    a = analyze_move(board, r, s, top_n=2, time_limit=1.0)
    assert a.side == "black" and a.best.term_changes["material"] > 800


def test_fork_refutation_and_alternatives():
    board = chess.Board(FORK)
    s = Searcher()
    r = s.search(board, max_depth=4)
    a = analyze_move(board, r, s, top_n=3, time_limit=1.0)
    assert a.best.san == "Nc7+"
    assert a.best.refutation is not None  # Black's king must move
    assert all(c.score < a.best.score for c in a.candidates[1:])


def test_pruning_estimate(italian):
    board, _, result = italian
    p = estimate_pruning(board, result)
    assert p.branching_factor > 20
    assert p.minimax_nodes > p.alphabeta_best_case > 0
    assert p.searched_nodes < p.minimax_nodes
    assert 0 < p.saved_pct < 100


def test_analyze_rejects_finished_game():
    board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")  # stalemate
    r = Searcher().search(board)
    with pytest.raises(ValueError):
        analyze_move(board, r)


# --------------------------------------------------------------- tree recorder


@pytest.mark.parametrize("fen", [ITALIAN, FORK, HANGING_QUEEN])
def test_tree_alphabeta_matches_minimax_with_less_work(fen):
    board = chess.Board(fen)
    ab = record_tree(board, depth=3, breadth=4, alpha_beta=True)
    mm = record_tree(board, depth=3, breadth=4, alpha_beta=False)
    assert ab.value == mm.value
    assert ab.best_move == mm.best_move
    assert mm.pruned == 0
    assert ab.visited <= mm.visited


def test_tree_structure():
    t = record_tree(chess.Board(ITALIAN), depth=3, breadth=3)
    root = t.root
    assert root.player == "max" and len(root.children) == 3
    assert all(c.player == "min" for c in root.children)
    assert t.pruned > 0  # with good ordering, something is cut off
    pruned = [n for n in _walk(root) if n.status == "pruned"]
    assert pruned and all(n.value is None and not n.children for n in pruned)
    cutters = [n for n in _walk(root) if n.caused_cutoff]
    assert cutters
    leaves = [n for n in _walk(root) if n.is_leaf]
    assert all(n.ply == 3 for n in leaves)  # no game ends this early here
    d = t.to_dict()
    json.dumps(d)
    assert d["root"]["alpha"] == "-inf" and d["root"]["beta"] == "+inf"


def test_tree_finds_the_fork():
    t = record_tree(chess.Board(FORK), depth=3, breadth=5)
    assert t.best_san == "Nc7+"


def test_tree_always_contains_the_engine_line():
    board = chess.Board(ITALIAN)
    r = Searcher().search(board, max_depth=4)
    t = record_tree(board, depth=3, breadth=2, pv=r.pv)
    node = t.root
    for move in r.pv[:3]:  # follow the engine's line down the tree
        node = next(c for c in node.children if c.move == move.uci())
        assert node.status == "searched"


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)
