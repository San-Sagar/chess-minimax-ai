"""Tactics benchmark: how many puzzles does each difficulty level solve, and how fast?

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\tactics.py                    # all levels
    .venv\\Scripts\\python scripts\\tactics.py --levels hard --csv docs\\tactics.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import time

from chess_ai import chess
from chess_ai.benchmark import PUZZLES
from chess_ai.engine.engine import Engine
from chess_ai.engine.levels import LEVELS, play_level_move


def solved(board: chess.Board, move: chess.Move, puzzle) -> bool:
    san = board.san(move)
    return san in puzzle.solutions if puzzle.solutions else san not in puzzle.avoid


def run_level(level_name: str, seed: int = 1) -> list[dict]:
    level = LEVELS[level_name]
    rows = []
    for p in PUZZLES:
        board = chess.Board(p.fen)
        engine = Engine(use_book=False)
        found_at = [None]

        def on_iteration(info, board=board, p=p, found_at=found_at):
            ok = solved(board, info.pv[0], p) if info.pv else False
            if ok and found_at[0] is None:
                found_at[0] = (info.depth, info.seconds)
            elif not ok:
                found_at[0] = None  # it changed its mind: not found yet

        start = time.perf_counter()
        choice = play_level_move(engine, board, level, random.Random(seed), analyze=False,
                                 on_iteration=on_iteration)
        seconds = time.perf_counter() - start
        ok = solved(board, choice.played, p)
        rows.append({
            "level": level_name, "puzzle": p.name, "theme": p.theme,
            "played": board.san(choice.played), "solved": ok,
            "found_depth": found_at[0][0] if ok and found_at[0] else None,
            "found_seconds": round(found_at[0][1], 3) if ok and found_at[0] else None,
            "seconds": round(seconds, 2),
            "weaker_on_purpose": choice.intended_san is not None,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--levels", nargs="*", default=list(LEVELS))
    parser.add_argument("--csv")
    args = parser.parse_args()

    all_rows = []
    for level in args.levels:
        rows = run_level(level)
        all_rows += rows
        print(f"\n== {LEVELS[level].label} ({LEVELS[level].description})")
        for r in rows:
            mark = "✓" if r["solved"] else "✗"
            found = (f"found at depth {r['found_depth']} ({r['found_seconds']}s)"
                     if r["found_depth"] else "")
            weak = " [weaker move on purpose]" if r["weaker_on_purpose"] else ""
            print(f"  {mark} {r['puzzle']:<30} played {r['played']:<7} {found}{weak}")
        n = sum(r["solved"] for r in rows)
        print(f"  -> {n}/{len(rows)} solved")

    print("\nSummary")
    for level in args.levels:
        rows = [r for r in all_rows if r["level"] == level]
        print(f"  {LEVELS[level].label:<9} {sum(r['solved'] for r in rows):>2}/{len(rows)}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
            w.writeheader()
            w.writerows(all_rows)
        print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
