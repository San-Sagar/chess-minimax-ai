"""Compare plain minimax, alpha-beta and the engine search (report material).

For each test position and depth it prints the score each algorithm found (they must
match), how many positions each visited, and how much alpha-beta saved.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\compare_search.py              # depths 1-3
    .venv\\Scripts\\python scripts\\compare_search.py --depth 4    # slow: minimax is huge
    .venv\\Scripts\\python scripts\\compare_search.py --csv docs\\search_comparison.csv
"""

from __future__ import annotations

import argparse
import csv
import time

from chess_ai import chess

from chess_ai.engine.classic import alphabeta, minimax
from chess_ai.engine.search import SearchConfig, Searcher

POSITIONS = {
    "Start": chess.STARTING_FEN,
    "Italian": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "Middlegame": "r2q1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2Q1RK1 w - - 0 10",
    "Endgame": "8/5pk1/6p1/8/3R4/6P1/5PKP/r7 w - - 0 40",
}


def timed(fn, *args):
    start = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--csv", help="also write the results to this CSV file")
    args = parser.parse_args()

    rows = []
    header = (f"{'Position':<11}{'D':>2}  {'Minimax nodes':>14}{'Alpha-beta':>12}"
              f"{'Engine':>10}{'Saved':>8}  {'Score':>7}  {'MM s':>6}{'AB s':>6}{'Eng s':>6}")
    print(header)
    print("-" * len(header))
    for name, fen in POSITIONS.items():
        board = chess.Board(fen)
        for depth in range(1, args.depth + 1):
            mm, mm_t = timed(minimax, board, depth)
            ab, ab_t = timed(alphabeta, board, depth)
            eng, eng_t = timed(
                lambda b, d: Searcher(SearchConfig.textbook()).search(b, max_depth=d),
                board, depth
            )
            eng_score = eng.score if board.turn == chess.WHITE else -eng.score
            agree = mm.score == ab.score == eng_score
            saved = 100 * (1 - ab.nodes / mm.nodes)
            print(f"{name:<11}{depth:>2}  {mm.nodes:>14,}{ab.nodes:>12,}{eng.stats.nodes:>10,}"
                  f"{saved:>7.1f}%  {mm.score:>+7}{'' if agree else ' MISMATCH!'}"
                  f"  {mm_t:>6.2f}{ab_t:>6.2f}{eng_t:>6.2f}")
            rows.append({
                "position": name, "depth": depth, "minimax_nodes": mm.nodes,
                "alphabeta_nodes": ab.nodes, "engine_nodes": eng.stats.nodes,
                "alphabeta_saved_pct": round(saved, 1), "score_white_cp": mm.score,
                "scores_agree": agree, "minimax_s": round(mm_t, 3),
                "alphabeta_s": round(ab_t, 3), "engine_s": round(eng_t, 3),
            })
    print("\nScore = centipawns from White's view; all three algorithms must agree.")
    print("Engine = negamax alpha-beta + iterative deepening (nodes summed over depths 1..D).")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
