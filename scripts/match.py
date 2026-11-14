"""Engine-vs-engine match: does a change actually make the AI play better?

Each opening is played twice with colours swapped, so neither engine gets an easier
opening. Games run in parallel processes.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\match.py full phase3 --time 0.3
    .venv\\Scripts\\python scripts\\match.py full phase3 --time 1 --workers 4 --pgn docs\\match.pgn

Engine names: full, phase3, textbook (see SearchConfig presets).
"""

from __future__ import annotations

import argparse
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor

from chess_ai import chess

from chess_ai.engine.search import SearchConfig, Searcher
from chess_ai.game import Game

PRESETS = {
    "full": SearchConfig,
    "phase3": SearchConfig.phase3,
    "textbook": SearchConfig.textbook,
}

OPENINGS = [
    "e4 e5 Nf3 Nc6", "d4 d5 c4 e6", "e4 c5 Nf3 d6", "d4 Nf6 c4 g6",
    "e4 e6 d4 d5", "c4 e5 Nc3 Nf6", "e4 c6 d4 d5", "Nf3 d5 g3 Nf6",
    "e4 e5 Nf3 Nf6", "d4 d5 Bf4 Nf6", "e4 d5 exd5 Qxd5", "d4 f5 g3 Nf6",
]
MAX_PLIES = 240  # adjudicate as a draw after this many half-moves


def play_game(args: tuple[str, str, str, float, int]) -> dict:
    white_name, black_name, opening, move_time, game_no = args
    engines = {chess.WHITE: Searcher(PRESETS[white_name]()),
               chess.BLACK: Searcher(PRESETS[black_name]())}
    game = Game()
    for san in opening.split():
        game.make_move(san)
    while not game.is_over and len(game.history) < MAX_PLIES:
        board = game.board
        result = engines[board.turn].search(board, time_limit=move_time)
        game.make_move(result.best_move)
    status = game.status()
    result = status.result if status.is_over else "1/2-1/2"
    pgn = game.to_pgn(white=white_name, black=black_name, event=f"Match game {game_no}")
    if not status.is_over:
        pgn = pgn.replace('[Result "*"]', '[Result "1/2-1/2"]')
    return {"game": game_no, "white": white_name, "black": black_name, "result": result,
            "reason": status.reason or "move_limit", "plies": len(game.history), "pgn": pgn}


def elo_difference(score: float) -> float:
    if score <= 0:
        return -math.inf
    if score >= 1:
        return math.inf
    return -400 * math.log10(1 / score - 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("engine_a", choices=PRESETS)
    parser.add_argument("engine_b", choices=PRESETS)
    parser.add_argument("--time", type=float, default=0.3, help="seconds per move")
    parser.add_argument("--openings", type=int, default=8)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--pgn", help="save all games to this PGN file")
    args = parser.parse_args()

    a, b = args.engine_a, args.engine_b
    jobs = []
    for i, opening in enumerate(OPENINGS[: args.openings]):
        jobs.append((a, b, opening, args.time, 2 * i + 1))
        jobs.append((b, a, opening, args.time, 2 * i + 2))

    print(f"{a} vs {b}: {len(jobs)} games, {args.time}s/move, {args.workers} workers\n")
    start = time.perf_counter()
    points = {a: 0.0, b: 0.0}
    wins_draws_losses = [0, 0, 0]  # from engine A's point of view
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(play_game, jobs):
            results.append(r)
            if r["result"] == "1-0":
                points[r["white"]] += 1
            elif r["result"] == "0-1":
                points[r["black"]] += 1
            else:
                points[r["white"]] += 0.5
                points[r["black"]] += 0.5
            a_won = (r["result"] == "1-0" and r["white"] == a) or \
                    (r["result"] == "0-1" and r["black"] == a)
            draw = r["result"] == "1/2-1/2"
            wins_draws_losses[0 if a_won else 1 if draw else 2] += 1
            print(f"  game {r['game']:>2}: {r['white']:>8} - {r['black']:<8} {r['result']:<8}"
                  f"{r['reason']:<22}{r['plies']:>4} plies")

    n = len(results)
    score = points[a] / n
    w, d, l_ = wins_draws_losses
    print(f"\n{a} {points[a]:g} - {points[b]:g} {b}   (+{w} ={d} -{l_})   "
          f"score {score:.1%}, Elo difference about {elo_difference(score):+.0f}")
    print(f"({time.perf_counter() - start:.0f}s; small matches are noisy: +/-100 Elo or more)")
    if args.pgn:
        with open(args.pgn, "w", encoding="utf-8") as f:
            f.write("\n\n".join(r["pgn"] for r in results) + "\n")
        print(f"Saved games to {args.pgn}")


if __name__ == "__main__":
    main()
