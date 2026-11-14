"""Search data for explaining a move ("why did the AI play that?").

After the engine has chosen a move, :func:`analyze_move` collects everything the AI
Thinking panel, the evaluation panel and the report need:

* **candidates**: the best few moves with *exact* scores, the line the engine expects
  after each, and the opponent reply that refutes the weaker ones. (Alpha-beta only
  proves the other moves are *worse*, it does not say by how much, so each candidate
  gets a short search of its own.)
* **term changes**: how each evaluation term (material, king safety...) changes along
  each candidate's line, so the explanation can say *what* a move achieves.
* **root moves**: what alpha-beta did with every legal move in the real search:
  searched first, proven worse and cut off (by which reply), re-searched...
* **pruning estimate**: positions searched vs. how many plain minimax would need.

Everything converts to plain dicts with ``to_dict()`` for the web API.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from chess_ai import chess

from chess_ai.engine.classic import MATE_SCORE
from chess_ai.engine.evaluation import TERMS, EvalBreakdown, compare, evaluate_breakdown
from chess_ai.engine.search import RootMoveStat, SearchResult, Searcher, format_score, mate_in


@dataclass(frozen=True)
class Candidate:
    move: chess.Move
    san: str
    score: int  # side to move's point of view (the AI's), exact at ``depth``
    depth: int
    line: list[chess.Move]  # starts with ``move``; expected continuation
    line_san: list[str]
    eval_after: EvalBreakdown  # static evaluation at the end of the line
    term_changes: dict[str, int]  # per term, from the AI's point of view (+ = good)
    is_best: bool

    @property
    def refutation(self) -> chess.Move | None:
        """The opponent's expected reply."""
        return self.line[1] if len(self.line) > 1 else None

    def to_dict(self) -> dict:
        return {
            "move": self.move.uci(), "san": self.san, "score": self.score,
            "score_text": format_score(self.score), "mate_in": mate_in(self.score),
            "depth": self.depth, "line": [m.uci() for m in self.line],
            "line_san": self.line_san,
            "refutation": self.refutation.uci() if self.refutation else None,
            "refutation_san": self.line_san[1] if len(self.line_san) > 1 else None,
            "eval_after": self.eval_after.to_dict(), "term_changes": self.term_changes,
            "is_best": self.is_best,
        }


@dataclass(frozen=True)
class PruningEstimate:
    """How much work alpha-beta saved, compared with plain minimax.

    Plain minimax visits every node: about ``1 + b + b^2 + ... + b^d`` for branching
    factor ``b`` and depth ``d``. A perfectly ordered alpha-beta search needs only about
    ``b^ceil(d/2) + b^floor(d/2) - 1`` leaf positions (Knuth & Moore, 1975). The engine
    can search even fewer, because null-move pruning, late-move reductions and futility
    pruning also skip branches that pure alpha-beta would still have to visit.
    """

    depth: int
    branching_factor: float  # average legal moves along the expected line
    minimax_nodes: int  # estimate for plain minimax to the same depth
    alphabeta_best_case: int  # leaves of a perfectly ordered alpha-beta tree
    searched_nodes: int  # main-search positions the engine actually visited
    quiescence_nodes: int  # extra capture-search positions
    saved_pct: float  # 100 * (1 - searched / minimax), up to 6 decimals
    one_in: int  # the engine searched 1 position for every ``one_in`` minimax would need

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "depth", "branching_factor", "minimax_nodes", "alphabeta_best_case",
            "searched_nodes", "quiescence_nodes", "saved_pct", "one_in")}


@dataclass
class MoveAnalysis:
    fen: str  # position the AI moved in
    side: str  # "white" / "black": the AI's colour
    best: Candidate
    candidates: list[Candidate]  # best first, then by score
    eval_before: EvalBreakdown
    root_moves: list[RootMoveStat]
    pruning: PruningEstimate
    search: dict  # depth, seldepth, nodes, nps, time, stats...
    iterations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fen": self.fen, "side": self.side,
            "best": self.best.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "eval_before": self.eval_before.to_dict(),
            "root_moves": [r.to_dict() for r in self.root_moves],
            "pruning": self.pruning.to_dict(),
            "search": self.search,
            "iterations": self.iterations,
        }


# ----------------------------------------------------------------------- helpers


def _line_san(board: chess.Board, line: list[chess.Move]) -> list[str]:
    b, out = board.copy(stack=False), []
    for m in line:
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


def _end_of_line(board: chess.Board, line: list[chess.Move]) -> chess.Board:
    b = board.copy()
    for m in line:
        if m not in b.legal_moves:
            break
        b.push(m)
    return b


def _term_changes(before: EvalBreakdown, after: EvalBreakdown, color: chess.Color) -> dict:
    """Change of each term along a line, from ``color``'s point of view."""
    sign = 1 if color == chess.WHITE else -1
    return {name: sign * delta for name, delta in compare(before, after).items()}


def _make_candidate(board: chess.Board, line: list[chess.Move], score: int, depth: int,
                    before: EvalBreakdown, is_best: bool) -> Candidate:
    after = evaluate_breakdown(_end_of_line(board, line))
    return Candidate(
        move=line[0], san=board.san(line[0]), score=score, depth=depth, line=line,
        line_san=_line_san(board, line), eval_after=after,
        term_changes=_term_changes(before, after, board.turn), is_best=is_best,
    )


def estimate_pruning(board: chess.Board, result: SearchResult) -> PruningEstimate:
    counts, b = [], board.copy()
    counts.append(b.legal_moves.count())
    for m in result.pv[: result.depth]:
        if m not in b.legal_moves:
            break
        b.push(m)
        n = b.legal_moves.count()
        if n:
            counts.append(n)
    bf = sum(counts) / len(counts)
    d = max(result.depth, 1)
    minimax_nodes = int(sum(bf ** i for i in range(d + 1)))
    best_case = int(bf ** math.ceil(d / 2) + bf ** math.floor(d / 2) - 1)
    searched = max(result.stats.nodes - result.stats.qnodes, 1)
    return PruningEstimate(
        depth=d, branching_factor=round(bf, 1), minimax_nodes=minimax_nodes,
        alphabeta_best_case=best_case, searched_nodes=searched,
        quiescence_nodes=result.stats.qnodes,
        saved_pct=round(max(0.0, 100 * (1 - searched / minimax_nodes)), 6),
        one_in=max(1, round(minimax_nodes / searched)),
    )


# ----------------------------------------------------------------------- main entry


def analyze_move(
    board: chess.Board,
    result: SearchResult,
    searcher: Searcher | None = None,
    top_n: int = 3,
    time_limit: float = 1.5,
) -> MoveAnalysis:
    """Explain-ready analysis of ``result`` (the engine's search of ``board``).

    ``searcher``: the searcher that produced ``result``; its transposition table is
    reused, which makes the candidate searches much cheaper.
    ``top_n``: number of candidates (including the chosen move).
    ``time_limit``: total seconds for the candidate searches.
    """
    if result.best_move is None:
        raise ValueError("no move to analyse (game over)")
    start = time.perf_counter()
    helper = Searcher(searcher.config if searcher else None)
    if searcher is not None:
        helper._tt = searcher._tt  # share what the main search already learned

    before = evaluate_breakdown(board)
    best = _make_candidate(board, result.pv, result.score, result.depth, before, True)

    # 1. Pick the most serious alternatives. The main search only proved them *worse*,
    #    but the bound it found is deep information: a move proven "at most -2.6" is
    #    out, one proven "at most +0.02" may be close. Ties (many moves share the same
    #    bound) are broken by a cheap 1-ply + capture-search score.
    deep_bound = {r.move: r.score for r in result.root_moves}
    ranked = []
    for m in board.legal_moves:
        if m == result.best_move:
            continue
        b = board.copy()
        b.push(m)
        shallow = -helper.search(b, max_depth=1).score
        ranked.append((deep_bound.get(m, shallow), shallow, m))
    ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)

    # 2. Search the top alternatives properly (same total depth as the real search).
    picked = [m for _, _, m in ranked[: max(top_n - 1, 0)]]
    remaining = time_limit - (time.perf_counter() - start)
    per_move = max(remaining, 0.1 * len(picked)) / max(len(picked), 1)
    candidates = [best]
    child_depth = max(result.depth - 1, 1)
    for m in picked:
        b = board.copy()
        b.push(m)
        r = helper.search(b, max_depth=child_depth, time_limit=per_move)
        if r.best_move is None:  # the move ends the game: checkmate or stalemate
            score, line, depth = (MATE_SCORE - 1 if b.is_checkmate() else 0), [m], 1
        else:
            score, line, depth = -r.score, [m, *r.pv], r.depth + 1
        candidates.append(_make_candidate(board, line, score, depth, before, False))
    candidates[1:] = sorted(candidates[1:], key=lambda c: c.score, reverse=True)

    last = result.iterations[-1] if result.iterations else None
    search_info = {
        "depth": result.depth,
        "seldepth": last.seldepth if last else 0,
        "nodes": result.stats.nodes,
        "seconds": round(result.seconds, 3),
        "nps": int(result.stats.nodes / result.seconds) if result.seconds else 0,
        "score": result.score, "score_text": result.score_text,
        "mate_in": result.mate_in,
        "timed_out": result.timed_out,
        "stats": result.stats.to_dict(),
        "legal_moves": board.legal_moves.count(),
    }
    return MoveAnalysis(
        fen=board.fen(), side="white" if board.turn == chess.WHITE else "black",
        best=best, candidates=candidates, eval_before=before,
        root_moves=result.root_moves, pruning=estimate_pruning(board, result),
        search=search_info, iterations=[i.to_dict() for i in result.iterations],
    )


__all__ = ["Candidate", "MoveAnalysis", "PruningEstimate", "TERMS", "analyze_move",
           "estimate_pruning"]
