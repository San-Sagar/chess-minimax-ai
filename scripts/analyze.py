"""Show all the data the AI records about one of its moves.

This is the raw material for the AI Thinking panel (Phase 9 turns it into sentences).

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\analyze.py --fen "<fen>" --time 3
    .venv\\Scripts\\python scripts\\analyze.py --moves e4 e5 Nf3 Nc6 Bc4 --json docs\\sample.json
"""

from __future__ import annotations

import argparse
import json
import time

import chess

from chess_ai.engine.analysis import analyze_move
from chess_ai.engine.evaluation import TERM_LABELS
from chess_ai.engine.search import Searcher, format_score
from chess_ai.engine.tree import record_tree


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fen", default=chess.STARTING_FEN)
    parser.add_argument("--moves", nargs="*", default=[])
    parser.add_argument("--time", type=float, default=3.0, help="seconds for the search")
    parser.add_argument("--json", help="also save everything as JSON to this file")
    args = parser.parse_args()

    board = chess.Board(args.fen)
    for m in args.moves:
        try:
            board.push_uci(m)
        except ValueError:
            board.push_san(m)

    searcher = Searcher()
    result = searcher.search(board, time_limit=args.time)
    t0 = time.perf_counter()
    a = analyze_move(board, result, searcher, top_n=3, time_limit=1.5)
    t_analysis = time.perf_counter() - t0
    t0 = time.perf_counter()
    tree = record_tree(board, depth=3, breadth=3, pv=result.pv)
    t_tree = time.perf_counter() - t0

    s = a.search
    print(f"Position: {board.fen()}   ({a.side} to move)\n")
    print(f"CHOSEN: {a.best.san}  {format_score(a.best.score)} (from the AI's side)   "
          f"line: {' '.join(a.best.line_san)}")
    print(f"Search: depth {s['depth']} (seldepth {s['seldepth']}), {s['nodes']:,} positions, "
          f"{s['seconds']}s, {s['nps']:,}/s")

    print("\nCANDIDATES (exact scores):")
    for c in a.candidates:
        changes = ", ".join(f"{TERM_LABELS[k]} {v:+d}" for k, v in
                            sorted(c.term_changes.items(), key=lambda kv: -abs(kv[1]))[:3]
                            if v)
        print(f"  {'*' if c.is_best else ' '} {c.san:<8}{format_score(c.score):>7}  "
              f"reply {c.line_san[1] if len(c.line_san) > 1 else '-':<7} "
              f"line {' '.join(c.line_san[:5]):<32} [{changes}]")

    print("\nHOW ALPHA-BETA HANDLED EACH ROOT MOVE (search order):")
    for r in a.root_moves[:12]:
        san = board.san(r.move)
        ref = ""
        if r.refutation:
            b = board.copy()
            b.push(r.move)
            ref = f"refuted by {b.san(r.refutation)}"
        kind = {"exact": "exact", "upper": "at most", "lower": "at least"}[r.bound]
        flags = (" (reduced)" if r.reduced else "") + (" (re-searched)" if r.researched else "")
        print(f"  {r.order + 1:>2}. {san:<8} {kind:<8} {format_score(r.score):>7} "
              f"{r.nodes:>7,} positions  {ref}{flags}")
    if len(a.root_moves) > 12:
        print(f"  ... {len(a.root_moves) - 12} more")

    p = a.pruning
    print(f"\nPRUNING: branching factor ~{p.branching_factor}, depth {p.depth}")
    print(f"  plain minimax would need ~{p.minimax_nodes:,} positions")
    print(f"  perfect alpha-beta needs   ~{p.alphabeta_best_case:,} leaf positions")
    print(f"  this search visited          {p.searched_nodes:,} "
          f"(+{p.quiescence_nodes:,} capture-search)")
    print(f"  -> 1 position for every {p.one_in:,} that minimax would need "
          f"({p.saved_pct:.4f}% skipped)")

    print(f"\nTREE VIEWER: depth {tree.depth}, breadth {tree.breadth}: visited "
          f"{tree.visited} of {tree.total} nodes ({tree.to_dict()['pruned_pct']}% pruned), "
          f"best {tree.best_san} {format_score(tree.value)}")
    print(f"\n(analysis {t_analysis:.2f}s, tree {t_tree:.2f}s)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"analysis": a.to_dict(), "tree": tree.to_dict()}, f, indent=1)
        print(f"Saved {args.json}")


if __name__ == "__main__":
    main()
