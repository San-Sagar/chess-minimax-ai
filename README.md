# Chess Playing AI Using Min/Max Algorithm

A chess engine written in Python that chooses its moves with the **minimax algorithm**
and **alpha-beta pruning**, with a web interface where a human plays against it and
can see *why* the AI chose each move.

## Features (planned)

- **Human vs AI:** pick a colour, difficulty and clock; undo, resign, flip board
- **Animated board:** drag-and-drop, legal-move dots, last-move and check highlights
- **Move history:** numbered move list, click to replay, captured pieces, PGN export
- **Evaluation panel:** eval bar, score graph, depth, nodes, nodes/sec, best line, top moves
- **AI Thinking panel:** a plain-language explanation of every AI move: its ideas,
  the alternatives it rejected and why, the line it expects, and how minimax and
  alpha-beta searched (nodes searched vs plain minimax, cutoffs)
- **Search tree viewer:** an interactive minimax tree with alpha/beta values and pruned branches
- **Learn page:** animated step-by-step lessons on minimax, alpha-beta and evaluation

## Project layout

```
chess_ai/
  game.py    game layer: moves, history, undo, endings, FEN/PGN
  engine/    evaluation function, minimax / alpha-beta search, move ordering, TT, perft
  explain/   turns search data into the AI Thinking narrative and tree viewer data
  server/    FastAPI backend (REST + WebSocket)
web/         frontend (board, panels, Learn page)
tests/       pytest test-suite
docs/        project report material
data/        opening books and endgame tablebases (not committed)
scripts/     benchmarking and strength-testing scripts
```

## Roadmap

| Phase | Work |
|---|---|
| 0 | Project setup ✅ |
| 1 | Rules (python-chess) ✅ |
| 2 | Evaluation function ✅ |
| 3 | Minimax → alpha-beta → iterative deepening → quiescence ✅ |
| 4 | Search speed-ups (move ordering, transposition table, pruning) |
| 5 | Search data recording |
| 6 | Opening book + endgame tablebases |
| 7 | Backend API |
| 8 | Board, move history, evaluation panel |
| 9 | AI Thinking panel + search tree viewer |
| 10 | Learn page |
| 11 | Strength testing |
| 12 | Project report |

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

## Play against the AI (terminal)

```powershell
.venv\Scripts\python scripts\play.py                      # you are White, 3 s per AI move
.venv\Scripts\python scripts\play.py --color black --time 5
```

## Compare minimax vs alpha-beta

```powershell
.venv\Scripts\python scripts\compare_search.py --depth 3 --csv docs\search_comparison.csv
```

## Inspect the evaluation

```powershell
.venv\Scripts\python scripts\eval.py --moves e4 e5 Nf3 Nc6   # term-by-term breakdown
.venv\Scripts\python scripts\eval.py --bench                 # evaluations per second
```

## Verify move generation (perft)

```powershell
.venv\Scripts\python scripts\perft.py --depth 4
```
