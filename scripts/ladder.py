"""Level ladder: play neighbouring difficulty levels against each other.

Each pair plays every opening twice (colours swapped). The result gives each level's
strength *relative to Beginner* in Elo, with a 95% error margin. Absolute ratings
(like a FIDE or Lichess rating) need games against rated opponents; see the report.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\ladder.py                      # beginner..hard, 12 games/pair
    .venv\\Scripts\\python scripts\\ladder.py --openings 4 --hard-time 1 --out docs\\ladder
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from chess_ai import chess
from chess_ai.benchmark import MatchScore, elo_with_margin
from chess_ai.engine.engine import Engine
from chess_ai.engine.levels import LEVELS, play_level_move
from chess_ai.game import Game

OPENINGS = [
    "e4 e5 Nf3 Nc6", "d4 d5 c4 e6", "e4 c5 Nf3 d6", "d4 Nf6 c4 g6",
    "e4 e6 d4 d5", "c4 e5 Nc3 Nf6", "e4 c6 d4 d5", "Nf3 d5 g3 Nf6",
]
MAX_PLIES = 220


def play_game(job: tuple) -> dict:
    white, black, opening, game_no, hard_time = job
    levels = {}
    for color, name in ((chess.WHITE, white), (chess.BLACK, black)):
        lv = LEVELS[name]
        if lv.max_depth is None and hard_time:
            lv = replace(lv, time_limit=hard_time)
        levels[color] = lv
    engines = {c: Engine(use_book=levels[c].use_book, seed=game_no * 2 + c) for c in levels}
    rngs = {c: random.Random(game_no * 7 + c) for c in levels}
    game = Game()
    for san in opening.split():
        game.make_move(san)
    while not game.is_over and len(game.history) < MAX_PLIES:
        board = game.board
        c = board.turn
        choice = play_level_move(engines[c], board, levels[c], rngs[c], analyze=False)
        game.make_move(choice.played)
    status = game.status()
    result = status.result if status.is_over else "1/2-1/2"
    pgn = game.to_pgn(white=LEVELS[white].label, black=LEVELS[black].label,
                      event=f"Level ladder game {game_no}")
    if not status.is_over:
        pgn = pgn.replace('[Result "*"]', '[Result "1/2-1/2"]')
    return {"white": white, "black": black, "result": result,
            "reason": status.reason or "move_limit", "plies": len(game.history), "pgn": pgn}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--levels", nargs="*", default=["beginner", "easy", "medium", "hard"])
    parser.add_argument("--openings", type=int, default=6)
    parser.add_argument("--hard-time", type=float, default=1.0,
                        help="seconds per move for the time-based levels (hard/master)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--out", help="write <out>.json and <out>.pgn")
    args = parser.parse_args()

    pairs = list(zip(args.levels, args.levels[1:]))
    jobs = []
    for weaker, stronger in pairs:
        for i, opening in enumerate(OPENINGS[: args.openings]):
            jobs.append((stronger, weaker, opening, len(jobs) + 1, args.hard_time))
            jobs.append((weaker, stronger, opening, len(jobs) + 1, args.hard_time))

    print(f"{len(jobs)} games ({len(pairs)} pairs x {2 * args.openings}), "
          f"time-based levels at {args.hard_time}s/move, {args.workers} workers\n")
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(play_game, jobs))

    summary = []
    cumulative = 0.0
    print(f"{'Pair':<22}{'+W':>4}{'=D':>4}{'-L':>4}  {'score':>6}  {'Elo diff':>14}   {'vs Beginner':>12}")
    for weaker, stronger in pairs:
        m = MatchScore()
        for r in results:
            if {r["white"], r["black"]} != {weaker, stronger}:
                continue
            strong_white = r["white"] == stronger
            if r["result"] == "1/2-1/2":
                m.draws += 1
            elif (r["result"] == "1-0") == strong_white:
                m.wins += 1
            else:
                m.losses += 1
        label = f"{LEVELS[stronger].label} vs {LEVELS[weaker].label}"
        if m.wins == m.n or m.losses == m.n:
            # a 100% / 0% score has no finite Elo: do not print a made-up number
            cumulative = None
            print(f"{label:<22}{m.wins:>4}{m.draws:>4}{m.losses:>4}  {m.score:>6.1%}  "
                  f"{'no finite Elo':>14}   {'n/a':>12}")
            summary.append({"stronger": stronger, "weaker": weaker, "wins": m.wins,
                            "draws": m.draws, "losses": m.losses, "score": round(m.score, 3),
                            "elo": None, "margin": None, "cumulative_vs_beginner": None})
            continue
        elo, margin = elo_with_margin(m.wins, m.draws, m.losses)
        cumulative = None if cumulative is None else cumulative + elo
        cum_text = "n/a" if cumulative is None else f"{cumulative:+.0f}"
        print(f"{label:<22}{m.wins:>4}{m.draws:>4}{m.losses:>4}  {m.score:>6.1%}  "
              f"{elo:>+7.0f} ± {margin:<5.0f}  {cum_text:>10}")
        summary.append({"stronger": stronger, "weaker": weaker, "wins": m.wins, "draws": m.draws,
                        "losses": m.losses, "score": round(m.score, 3), "elo": round(elo),
                        "margin": round(margin),
                        "cumulative_vs_beginner": None if cumulative is None else round(cumulative)})
    reasons = {}
    for r in results:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    print(f"\nGame endings: {reasons}")
    print(f"({time.perf_counter() - start:.0f}s. A score of 100% or 0% gives no finite Elo; "
          "the margin shows how uncertain a small match is.)")
    if args.out:
        with open(args.out + ".json", "w", encoding="utf-8") as f:
            json.dump({"settings": vars(args), "pairs": summary, "endings": reasons}, f, indent=1)
        with open(args.out + ".pgn", "w", encoding="utf-8") as f:
            f.write("\n\n".join(r["pgn"] for r in results) + "\n")
        print(f"Wrote {args.out}.json and {args.out}.pgn")


if __name__ == "__main__":
    main()
