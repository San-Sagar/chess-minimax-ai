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
  engine/    evaluation function, minimax / alpha-beta search, move ordering, TT
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
| 1 | Rules (python-chess) |
| 2 | Evaluation function |
| 3 | Minimax → alpha-beta → iterative deepening → quiescence |
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
