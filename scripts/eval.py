"""Show how the AI evaluates a position, term by term.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\eval.py                      # starting position
    .venv\\Scripts\\python scripts\\eval.py --fen "<fen>"
    .venv\\Scripts\\python scripts\\eval.py --moves e4 e5 Nf3     # play moves first
    .venv\\Scripts\\python scripts\\eval.py --bench               # evaluations per second
"""

from __future__ import annotations

import argparse
import time

import chess

from chess_ai.engine.evaluation import TERM_LABELS, evaluate, evaluate_breakdown


def show(board: chess.Board) -> None:
    b = evaluate_breakdown(board)
    print(board.unicode(invert_color=True, borders=True))
    print(f"\nFEN: {board.fen()}")
    print(f"Phase: {b.phase}/24 ({'middlegame' if b.phase > 12 else 'endgame'}-ish)\n")
    print(f"{'Term':<22}{'White':>8}{'Black':>8}{'Net':>8}")
    print("-" * 46)
    for name, t in b.terms.items():
        print(f"{TERM_LABELS[name]:<22}{t.white:>8}{t.black:>8}{t.net:>+8}")
    print("-" * 46)
    side = "White" if b.total >= 0 else "Black"
    print(f"{'Total (White view)':<38}{b.total:>+8}   = {b.total / 100:+.2f} pawns, "
          f"{side} {'better' if b.total else 'equal'}")


def bench(board: chess.Board, seconds: float = 2.0) -> None:
    n, start = 0, time.perf_counter()
    while time.perf_counter() - start < seconds:
        for _ in range(200):
            evaluate(board)
        n += 200
    elapsed = time.perf_counter() - start
    print(f"{n / elapsed:,.0f} evaluations/second")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fen", default=chess.STARTING_FEN)
    parser.add_argument("--moves", nargs="*", default=[], help="moves in SAN or UCI")
    parser.add_argument("--bench", action="store_true")
    args = parser.parse_args()

    board = chess.Board(args.fen)
    for m in args.moves:
        try:
            board.push_uci(m)
        except ValueError:
            board.push_san(m)
    if args.bench:
        bench(board)
    else:
        show(board)


if __name__ == "__main__":
    main()
