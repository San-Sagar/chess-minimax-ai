# Strength report: Chess Minimax AI

All numbers below were produced by the scripts in `scripts/` on the development laptop
(8 logical CPUs, Python 3.11). Re-run them to reproduce.

## 1. Correctness first

| Check | Result |
|---|---|
| Move generator (perft, 5 standard positions, 7.0 M positions) | all counts exact |
| Cross-check vs. an independent rules library, 300 random games / 54,350 positions (before it was removed) | 0 mismatches |
| Minimax = alpha-beta = engine (textbook mode), depths 1-3, 5 positions | identical scores |
| Move ordering + PVS + aspiration leave the depth-4 score unchanged | identical scores |
| Test suite | 387 tests passing |

## 2. Tactics (`scripts/tactics.py`, results in `docs/tactics.csv`)

15 puzzles: 7 checkmates (mate in 1 and 2), 6 material-winning tactics (free piece,
knight fork, pawn fork, skewer, discovered check, promotion) and 2 traps to avoid (a
poisoned pawn that loses the queen to the horizon effect, and a stalemate trap).

The mate answers are **proven by brute force** (`chess_ai.benchmark.mating_moves`):
an exhaustive search using only the rules of chess, no evaluation function, so the
answer key does not depend on the AI being tested. The other answers were confirmed by
an 8-second reference search (depth 8-15).

| Level | Solved | Missed |
|---|---|---|
| Beginner (depth 1, random among close moves) | 13 / 15 | quiet king move then mate (needs depth 3); pawn fork |
| Easy (depth 2, random among close moves) | 13 / 15 | both mates in 2 (need 3 plies) |
| Medium (depth 4) | **15 / 15** | |
| Hard (3 s) | **15 / 15** | |
| Master (8 s) | **15 / 15** | |

Interpretation: the shallow levels miss exactly the puzzles that need more look-ahead
than their depth limit, which is what minimax predicts. The puzzle set is basic; it
shows correct tactical play but does not separate Medium, Hard and Master. The level
ladder below does.

## 3. Search efficiency (`scripts/compare_search.py`, `scripts/ablation.py`)

Plain minimax vs alpha-beta, depth 3, same score every time:

| Position | Minimax | Alpha-beta | Skipped |
|---|---|---|---|
| Start | 9,323 | 780 | 91.6% |
| Italian Game | 31,506 | 3,293 | 89.5% |
| Middlegame | 60,420 | 4,026 | 93.3% |
| Rook endgame | 9,653 | 1,230 | 87.3% |

Techniques added one at a time, positions searched to depth 4 (four positions):

| Technique | Positions | vs alpha-beta + quiescence |
|---|---|---|
| Alpha-beta + quiescence | 707,165 | 100% |
| + move ordering | 216,758 | 30.7% |
| + transposition table | 146,959 | 20.8% |
| + principal variation search | 77,258 | 10.9% |
| + null-move pruning | 56,250 | 8.0% |
| + late-move reductions | 21,365 | 3.0% |
| Full engine | 16,782 | 2.4% |

Speed: about 15,000-20,000 positions per second (pure Python). In 3 seconds the full
engine reaches depth 6-7 in typical positions (longest lines 14-20 plies with
quiescence and extensions).

Earlier match (Phase 4): full engine vs alpha-beta + quiescence only, 16 games at
0.5 s/move: **+14 =2 -0** (about +470 Elo, very uncertain with so few games).

## 4. Level ladder (`scripts/ladder.py`, games in `docs/ladder.pgn`)

Neighbouring levels played 12 games each (6 openings, each with colours swapped).
Hard played at 1 second per move instead of 3 to keep the run time reasonable.
36 games in 7.5 minutes: 32 ended in checkmate, 2 by insufficient material, 1 by
threefold repetition, 1 by the move limit.

| Pair | Result (+W =D −L) | Score | Elo difference (95% margin) |
|---|---|---|---|
| Easy vs Beginner | +12 =0 −0 | 100% | no finite value: Easy won every game |
| Medium vs Easy | +11 =0 −1 | 91.7% | about +420 (± 500) |
| Hard (1 s) vs Medium | +6 =4 −2 | 66.7% | about +120 (± 190) |

Reading the table:

* Every level beat the level below it, so the levels are in the right order.
* A 12-0 score cannot be turned into an Elo number (the formula gives infinity); it
  only says the gap is large.
* With 12 games per pair the margins are wide; hundreds of games would be needed for
  precise numbers. The direction of every result is clear, the exact size is not.
* The gap shrinks as levels get stronger (Hard vs Medium is closest), as expected:
  extra depth helps less once the engine already sees most tactics.

## 5. What can and cannot be claimed

* **Relative strength is measured**: the ladder shows each level is clearly stronger
  than the one below, with error margins.
* **Absolute Elo is not measured.** An Elo number is only meaningful against a rated
  pool. The project uses no outside engine or rating data, so no FIDE / Lichess number
  can be claimed from these tests.
* **Honest estimate**: the full engine searches 6-7 plies with quiescence, has a sound
  evaluation and opening book, and solved every tactic in the suite. Engines with this
  profile typically play at **strong club level (roughly 1500-1900)**. This is an
  estimate, not a measurement. It is far from grandmaster strength (2500+), which in
  Python would need a much faster search or a neural-network evaluation.
* **How to measure it properly** (future work): play rated games online (e.g. as a
  Lichess bot), or play matches against a reference engine at known strength settings.
  This is testing only; the AI itself stays fully our own code.

## 6. Known weaknesses

* **Endgame technique**: without endgame-specific knowledge the AI can fail to convert
  some won endgames within the move limit (seen in a Phase 4 match game).
* **Speed**: pure Python is roughly 50-100 times slower than C/C++ engines, which limits
  depth.
* **Evaluation**: hand-tuned values, not tuned on game data.
