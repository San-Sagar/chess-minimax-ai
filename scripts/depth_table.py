"""Nodes evaluated and time per move at increasing depth: Min-Max vs Alpha-Beta.

Fair timing: the evaluation cache is cleared before every run, so no algorithm benefits
from positions another one already evaluated.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\depth_table.py --depths 2 3 4 5 --csv docs\\depth_table.csv
"""

from __future__ import annotations

import argparse
import csv
import time

from chess_ai import chess
from chess_ai.engine import evaluation
from chess_ai.engine.classic import alphabeta, minimax
from chess_ai.engine.search import Searcher

POSITIONS = {
    "start": chess.STARTING_FEN,
    "italian": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
}


def timed(fn, *args):
    evaluation._EVAL_CACHE.clear()
    start = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--position", choices=POSITIONS, default="start")
    parser.add_argument("--depths", type=int, nargs="*", default=[2, 3, 4, 5])
    parser.add_argument("--csv")
    args = parser.parse_args()

    board = chess.Board(POSITIONS[args.position])
    rows = []
    print(f"{'D':>2} {'Min-Max nodes':>14} {'time s':>8} {'Alpha-Beta nodes':>17} {'time s':>8} "
          f"{'reduction':>10} {'engine nodes':>13} {'time s':>8} same")
    for d in args.depths:
        mm, mm_t = timed(minimax, board, d)
        ab, ab_t = timed(alphabeta, board, d)
        eng, eng_t = timed(lambda b, dd: Searcher().search(b, max_depth=dd), board, d)
        red = 100 * (1 - ab.nodes / mm.nodes)
        same = mm.score == ab.score
        print(f"{d:>2} {mm.nodes:>14,} {mm_t:>8.2f} {ab.nodes:>17,} {ab_t:>8.2f} {red:>9.1f}% "
              f"{eng.stats.nodes:>13,} {eng_t:>8.2f} {same}", flush=True)
        rows.append({"position": args.position, "depth": d, "minimax_nodes": mm.nodes,
                     "minimax_s": round(mm_t, 3), "alphabeta_nodes": ab.nodes,
                     "alphabeta_s": round(ab_t, 3), "reduction_pct": round(red, 2),
                     "engine_nodes": eng.stats.nodes, "engine_s": round(eng_t, 3),
                     "same_score": same, "score_cp": mm.score})
        if args.csv:  # write after every depth so partial results survive
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)


if __name__ == "__main__":
    main()
