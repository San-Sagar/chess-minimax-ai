"""Measure what each search technique adds (report material).

Starts from the Phase 3 engine (alpha-beta + quiescence) and switches techniques on
one at a time, cumulatively, measuring positions searched and time to reach a fixed
depth on several positions.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\ablation.py                 # depth 4
    .venv\\Scripts\\python scripts\\ablation.py --depth 5 --csv docs\\ablation.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import replace

import chess

from chess_ai.engine import evaluation
from chess_ai.engine.search import SearchConfig, Searcher

POSITIONS = {
    "Start": chess.STARTING_FEN,
    "Italian": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "Middlegame": "r2q1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2Q1RK1 w - - 0 10",
    "Endgame": "8/5pk1/6p1/8/3R4/6P1/5PKP/r7 w - - 0 40",
}

STEPS = [  # (label, field switched on)
    ("Alpha-beta + quiescence (Phase 3)", None),
    ("+ move ordering", "move_ordering"),
    ("+ transposition table", "transposition_table"),
    ("+ principal variation search", "pvs"),
    ("+ aspiration windows", "aspiration"),
    ("+ null-move pruning", "null_move"),
    ("+ late move reductions", "late_move_reductions"),
    ("+ futility pruning", "futility"),
    ("+ check extension (full engine)", "check_extension"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--csv")
    args = parser.parse_args()

    cfg = SearchConfig.phase3()
    rows = []
    print(f"Positions searched to depth {args.depth} (sum over {len(POSITIONS)} positions)\n")
    print(f"{'Technique':<38}{'Nodes':>12}{'vs Phase 3':>12}{'Time s':>9}{'Nodes/s':>10}")
    print("-" * 81)
    base_nodes = None
    for label, flag in STEPS:
        if flag:
            cfg = replace(cfg, **{flag: True})
        nodes, seconds = 0, 0.0
        for fen in POSITIONS.values():
            evaluation._EVAL_CACHE.clear()  # fair comparison: no warm cache
            start = time.perf_counter()
            r = Searcher(cfg).search(chess.Board(fen), max_depth=args.depth)
            seconds += time.perf_counter() - start
            nodes += r.stats.nodes
        base_nodes = base_nodes or nodes
        print(f"{label:<38}{nodes:>12,}{nodes / base_nodes:>11.1%} {seconds:>9.2f}"
              f"{nodes / seconds:>10,.0f}")
        rows.append({"technique": label, "depth": args.depth, "nodes": nodes,
                     "fraction_of_phase3": round(nodes / base_nodes, 4),
                     "seconds": round(seconds, 2)})
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
