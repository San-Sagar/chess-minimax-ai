"""Run perft on the reference positions and report correctness and speed.

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\perft.py            # depth up to 4 (default)
    .venv\\Scripts\\python scripts\\perft.py --depth 5  # slower, more thorough
    .venv\\Scripts\\python scripts\\perft.py --fen "<fen>" --depth 3 --divide
"""

from __future__ import annotations

import argparse
import sys

from chess_ai import chess

from chess_ai.engine.perft import REFERENCE_POSITIONS, divide, timed_perft


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--fen", help="run on a custom position instead of the reference set")
    parser.add_argument("--divide", action="store_true", help="show counts per first move")
    args = parser.parse_args()

    if args.fen:
        board = chess.Board(args.fen)
        if args.divide:
            for move, count in sorted(divide(board, args.depth).items()):
                print(f"{move}: {count}")
        r = timed_perft(board, args.depth)
        print(f"depth {r.depth}: {r.nodes:,} nodes in {r.seconds:.2f}s "
              f"({r.nodes_per_second:,.0f} nodes/s)")
        return 0

    failures = 0
    total_nodes, total_time = 0, 0.0
    for name, (fen, expected) in REFERENCE_POSITIONS.items():
        for depth in range(1, min(args.depth, len(expected)) + 1):
            r = timed_perft(chess.Board(fen), depth)
            ok = r.nodes == expected[depth - 1]
            failures += not ok
            total_nodes += r.nodes
            total_time += r.seconds
            print(f"{'PASS' if ok else 'FAIL'}  {name:<10} depth {depth}: {r.nodes:>10,} "
                  f"(expected {expected[depth - 1]:>10,})  {r.seconds:6.2f}s")
    nps = total_nodes / total_time if total_time else 0
    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}  "
          f"{total_nodes:,} nodes in {total_time:.1f}s ({nps:,.0f} nodes/s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
