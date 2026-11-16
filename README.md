# Chess Playing AI Using Min/Max Algorithm

A chess engine written in Python that chooses its moves with the **minimax algorithm**
and **alpha-beta pruning**, with a web interface where a human plays against it and
can see *why* the AI chose each move.

**Everything is written from scratch for this project:** the chess rules (bitboard
board, legal move generation, FEN/SAN/PGN), the evaluation function, minimax, alpha-beta
and all search techniques, and the opening book. No chess library or downloaded chess
data is used. The move generator is verified with perft against the published counts.
(The optional 3D views use the Three.js graphics library for drawing only.)

## Features

- **Human vs AI:** pick a colour, difficulty and clock; undo, resign, flip board
- **Three board styles** (buttons at the top, the choice is remembered):
  - **Plain:** flat animated board: drag-and-drop, legal-move dots, last-move and check highlights
  - **3D:** carved wooden pieces on a wooden board (shapes and wood grain generated in code),
    drag or click to move, rotate / zoom the camera, a 360° fly-around before each game
  - **Battle:** the pieces are soldiers on a battlefield and every capture is a fight:
    spearman (pawn) stabs, horse archer (knight) shoots, javelin priest (bishop) throws,
    war elephant (rook) shoots from its tower and charges, sorceress (queen) calls lightning,
    warlord-mage (king) releases a shockwave. Armies march in, a mated king kneels.
    Speed control: 1× / 2× / Skip. Battle sounds are synthesised with the Web Audio API.
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
  chess/     the rules of chess: bitboards, attacks, legal moves, FEN, SAN, PGN
  game.py    game layer: moves, history, undo, endings, FEN/PGN
  engine/    evaluation, minimax / alpha-beta search, move ordering, TT, opening book,
             move analysis, search-tree recorder, perft
  explain/   turns search data into the AI Thinking narrative and tree viewer data
  server/    FastAPI backend (REST + WebSocket)
web/         frontend (board, panels, Learn page)
tests/       pytest test-suite
docs/        project report material
data/        scratch output (not committed)
scripts/     benchmarking and strength-testing scripts
```

## Roadmap

| Phase | Work |
|---|---|
| 0 | Project setup ✅ |
| 1 | Rules: own bitboard move generator, FEN/SAN/PGN ✅ |
| 2 | Evaluation function ✅ |
| 3 | Minimax → alpha-beta → iterative deepening → quiescence ✅ |
| 4 | Search speed-ups (move ordering, transposition table, pruning) ✅ |
| 5 | Search data recording ✅ |
| 6 | Curated opening book + opening names ✅ |
| 7 | Backend API (REST + WebSocket live thinking) ✅ |
| 8 | Board, move history, evaluation panel (own HTML/CSS/JS, no libraries) ✅ |
| 9 | AI Thinking panel + search tree viewer ✅ |
| 10 | Learn page: animated minimax / alpha-beta lessons ✅ |
| 11 | Strength testing: tactics suite, level ladder, report (`docs/strength_report.md`) ✅ |
| 12 | Project report ✅ |
| 13 | Board style switch (Plain / 3D / Battle) ✅ |
| 14 | 3D board: carved pieces, wood textures, 360° intro ✅ |
| 15 | Battle mode: armies and battlefield ✅ |
| 16 | Battle mode: attack animations, march-in, sounds, speed control ✅ |
| 17 | Phone performance, release ✅ |

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

## Deploy (Hugging Face Spaces)

The app runs online as a Docker Space that builds straight from this repository:

1. Create a Space: **SDK = Docker, template = Blank, visibility = Public**.
2. Add the two files from [`deploy/huggingface/`](deploy/huggingface/) (`README.md`, `Dockerfile`).
3. The Space builds and starts on port 7860. To publish a new version later: push to
   GitHub, then **Settings → Factory rebuild** on the Space.

Server settings (environment variables): `CHESS_MAX_AI_SECONDS` (cap on AI thinking time,
default 5 in Docker), `CHESS_MAX_SEARCHES` (AI searches allowed at once, default 2),
`CHESS_QUEUE_TIMEOUT` (seconds a move may wait for a free slot, default 60).

Run the same production image locally:

```powershell
docker build -t chess-minimax-ai .
docker run -p 7860:7860 chess-minimax-ai      # http://localhost:7860
```

## Run the server

```powershell
.venv\Scripts\python -m chess_ai.server            # http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 to play. The page (`web/`) is plain HTML, CSS and JavaScript
modules written for this project: `board.js` (board, animation, drag and drop, promotion),
`panels.js` (move history, eval bar, score graph, live search), `app.js` (game flow),
`sound.js` (move and battle sounds made with the Web Audio API).

The 3D views: `boardhost.js` (switches between Plain / 3D / Battle behind one interface),
`board3d.js` (3D board, camera, input, intro), `pieces3d.js` (lathe-turned pieces),
`textures3d.js` (wood, stone and sky painted in code), `units3d.js` (the battle units and
their jointed rigs), `battle3d.js` (battlefield, attack choreography, move queue).
They use [Three.js](https://threejs.org) r170 (MIT licence), kept in `web/vendor/three/`
and loaded only when 3D or Battle is chosen. Three.js only draws the graphics: the chess
rules, the AI and every model and texture are this project's own code. On phones the 3D
views use lighter settings, and they lower their quality by themselves on a slow device.
Without WebGL the page falls back to the Plain board.

API docs (interactive) at http://127.0.0.1:8000/docs. Main endpoints: `POST /api/games`,
`POST /api/games/{id}/move`, `POST /api/games/{id}/ai-move`, `GET /api/games/{id}/tree`,
and the WebSocket `/ws/games/{id}`, which streams the AI's search depth by depth.
Difficulty levels: beginner, easy, medium, hard, master.

## Play against the AI (terminal)

```powershell
.venv\Scripts\python scripts\play.py                      # you are White, 3 s per AI move
.venv\Scripts\python scripts\play.py --color black --time 5
```

## Compare minimax vs alpha-beta

```powershell
.venv\Scripts\python scripts\compare_search.py --depth 3 --csv docs\search_comparison.csv
```

## See what the AI records about a move

```powershell
.venv\Scripts\python scripts\analyze.py --moves e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 --time 3
```

## Measure each search technique / play engine matches

```powershell
.venv\Scripts\python scripts\ablation.py --depth 4 --csv docs\ablation_depth4.csv
.venv\Scripts\python scripts\match.py full phase3 --time 0.5 --pgn docs\match.pgn
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
