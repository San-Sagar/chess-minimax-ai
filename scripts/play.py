"""Play against the AI in the terminal (a stopgap until the web UI in Phase 8).

Usage (from the project folder):
    .venv\\Scripts\\python scripts\\play.py                    # you are White, 3 s per AI move
    .venv\\Scripts\\python scripts\\play.py --color black --time 5

Type moves as SAN (e4, Nf3, O-O, exd5, e8=Q) or UCI (e2e4).
Commands: undo, moves, pgn, resign, quit
"""

from __future__ import annotations

import argparse

from chess_ai import chess

from chess_ai.engine.search import IterationInfo, Searcher
from chess_ai.game import BLACK, WHITE, Game, IllegalMoveError


def show(game: Game, human: str) -> None:
    board = game.board
    print()
    print(board.unicode(invert_color=True, borders=True, orientation=human == WHITE))
    last = game.last_move
    if last:
        print(f"Last move: {last.move_number}{'.' if last.color == WHITE else '...'} {last.san}")
    if game.is_check:
        print("Check!")


def print_iteration(board: chess.Board):
    def _print(info: IterationInfo) -> None:
        line = board.variation_san(info.pv) if info.pv else ""
        print(f"  depth {info.depth:>2}  score {info.to_dict()['score_text']:>7}  "
              f"nodes {info.nodes:>9,}  {info.nps:>7,} n/s  {info.seconds:5.1f}s  {line}")
    return _print


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--color", choices=[WHITE, BLACK], default=WHITE)
    parser.add_argument("--time", type=float, default=3.0, help="seconds per AI move")
    parser.add_argument("--fen", default=chess.STARTING_FEN)
    args = parser.parse_args()

    game, human, searcher = Game(args.fen), args.color, Searcher()
    print(__doc__.split("\n\n", 1)[1])

    while not game.is_over:
        show(game, human)
        if game.turn == human:
            text = input("\nYour move: ").strip()
            if text in ("quit", "exit"):
                return
            if text == "resign":
                game.resign(human)
                break
            if text == "moves":
                print(" ".join(sorted(game.board.san(m) for m in game.board.legal_moves)))
                continue
            if text == "pgn":
                print(game.to_pgn())
                continue
            if text == "undo":
                try:
                    game.undo(2 if len(game.history) >= 2 else 1)
                except IllegalMoveError as exc:
                    print(exc)
                continue
            try:
                game.make_move(text)
            except IllegalMoveError as exc:
                print(f"  {exc}")
        else:
            print("\nAI is thinking...")
            board = game.board
            result = searcher.search(board, time_limit=args.time,
                                     on_iteration=print_iteration(board))
            rec = game.make_move(result.best_move)
            print(f"AI plays {rec.san}  (eval {result.score_text} for AI, "
                  f"depth {result.depth}, {result.stats.nodes:,} positions)")

    show(game, human)
    s = game.status()
    print(f"\nGame over: {s.reason.replace('_', ' ')}, "
          f"{'draw' if s.winner is None else s.winner + ' wins'} ({s.result})")
    print("\n" + game.to_pgn(white="You" if human == WHITE else "AI",
                             black="AI" if human == WHITE else "You"))


if __name__ == "__main__":
    main()
