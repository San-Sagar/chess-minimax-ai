"""The engine's search: how the AI actually picks its move.

It is the same minimax with alpha-beta as ``classic.py``, written in the shorter
**negamax** form. Instead of separate "max" and "min" branches, every score is from the
side to move's point of view and is negated when passed up the tree, because
``max(a, b) == -min(-a, -b)``. Tests check it returns exactly the textbook scores.

On top of alpha-beta it adds:

* **Quiescence search**: at the end of the planned depth, keep searching *captures*
  until the position is quiet. Otherwise the AI might stop calculating halfway through
  a trade, think "I just won a pawn", and miss that its queen is taken back
  (the "horizon effect").
* **Iterative deepening**: search depth 1, then 2, then 3... until the time runs out.
  The AI always has a finished answer ready, and the best move from the previous depth
  is tried first, which makes alpha-beta cut off much more.
* **Mate and draw scoring**: checkmate = +/-MATE_SCORE (sooner mates score higher),
  stalemate / repetition / 50 moves / insufficient material = 0.
* **Statistics** (nodes, cutoffs, depth...) for the evaluation panel and the report.

Phase 4 adds move ordering, a transposition table and further pruning to ``Searcher``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import chess

from chess_ai.engine.classic import INFINITY, MATE_SCORE, is_draw
from chess_ai.engine.evaluation import evaluate
from chess_ai.engine.tables import MG_VALUE

MAX_PLY = 128
MATE_THRESHOLD = MATE_SCORE - MAX_PLY  # scores beyond this are "mate in N"
_TIME_CHECK_EVERY = 1024  # nodes between clock checks


class _Timeout(Exception):
    """Raised inside the search when the time limit is reached."""


# ----------------------------------------------------------------------- results


def mate_in(score: int) -> int | None:
    """Moves to mate (positive: side to move mates, negative: gets mated), or None."""
    if abs(score) < MATE_THRESHOLD:
        return None
    plies = MATE_SCORE - abs(score)
    moves = (plies + 1) // 2
    return moves if score > 0 else -moves


def format_score(score: int) -> str:
    """'+0.35', '-1.20', '#3' (mate in 3), '#-2' (getting mated in 2)."""
    m = mate_in(score)
    if m is not None:
        return f"#{m}"
    return f"{score / 100:+.2f}"


@dataclass
class SearchStats:
    nodes: int = 0  # every position visited (main search + quiescence)
    qnodes: int = 0  # of which in quiescence search
    cutoffs: int = 0  # alpha-beta cutoffs (move lists abandoned early)
    seldepth: int = 0  # deepest ply reached, including quiescence


@dataclass(frozen=True)
class IterationInfo:
    """Result of one completed iteration of iterative deepening (live UI update)."""

    depth: int
    score: int  # side to move's point of view
    pv: list[chess.Move]  # principal variation: the line both sides are expected to play
    nodes: int
    cutoffs: int
    seldepth: int
    seconds: float

    @property
    def nps(self) -> int:
        return int(self.nodes / self.seconds) if self.seconds > 0 else 0

    def to_dict(self) -> dict:
        return {
            "depth": self.depth, "score": self.score, "score_text": format_score(self.score),
            "mate_in": mate_in(self.score), "pv": [m.uci() for m in self.pv],
            "nodes": self.nodes, "cutoffs": self.cutoffs, "seldepth": self.seldepth,
            "seconds": round(self.seconds, 3), "nps": self.nps,
        }


@dataclass
class SearchResult:
    best_move: chess.Move | None  # None only if there are no legal moves
    score: int  # side to move's point of view, centipawns (or mate score)
    pv: list[chess.Move]
    depth: int  # last fully completed depth
    stats: SearchStats
    seconds: float
    iterations: list[IterationInfo] = field(default_factory=list)
    timed_out: bool = False  # True if the clock stopped a deeper iteration

    @property
    def mate_in(self) -> int | None:
        return mate_in(self.score)

    @property
    def score_text(self) -> str:
        return format_score(self.score)


# ----------------------------------------------------------------------- ordering


def mvv_lva(board: chess.Board, move: chess.Move) -> int:
    """'Most Valuable Victim, Least Valuable Attacker': try QxP last, PxQ first."""
    if board.is_en_passant(move):
        victim = chess.PAWN
    else:
        piece = board.piece_type_at(move.to_square)
        victim = piece if piece else 0
    attacker = board.piece_type_at(move.from_square) or chess.PAWN
    score = (MG_VALUE[victim] if victim else 0) * 10 - MG_VALUE[attacker] // 10
    if move.promotion:
        score += MG_VALUE[move.promotion] * 10
    return score


# ----------------------------------------------------------------------- search


class Searcher:
    """Negamax alpha-beta search with quiescence and iterative deepening.

    >>> result = Searcher().search(chess.Board(), max_depth=4)
    >>> result.best_move, result.score_text
    """

    def __init__(self, quiescence: bool = True) -> None:
        self.quiescence = quiescence
        self.stats = SearchStats()
        self._deadline: float | None = None
        self._root_best: chess.Move | None = None

    # ---------------------------------------------------------- public

    def search(
        self,
        board: chess.Board,
        max_depth: int | None = None,
        time_limit: float | None = None,
        on_iteration: Callable[[IterationInfo], None] | None = None,
    ) -> SearchResult:
        """Find the best move.

        * ``max_depth``: stop after this many plies (half-moves).
        * ``time_limit``: seconds; deeper iterations are abandoned when time runs out
          (depth 1 always completes so there is always a move).
        * ``on_iteration``: called after every completed depth (live UI updates).

        With neither limit given, searches to depth 4.
        """
        if max_depth is None and time_limit is None:
            max_depth = 4
        max_depth = min(max_depth or MAX_PLY, MAX_PLY)

        board = board.copy()  # never touch the caller's board
        self.stats = SearchStats()
        self._root_best = None
        start = time.perf_counter()

        legal = list(board.legal_moves)
        if not legal:
            score = -MATE_SCORE if board.is_check() else 0
            return SearchResult(None, score, [], 0, self.stats, 0.0)

        result = SearchResult(legal[0], 0, [legal[0]], 0, self.stats, 0.0)
        for depth in range(1, max_depth + 1):
            # The clock only applies once depth 1 is done, so a move always exists.
            self._deadline = start + time_limit if (time_limit and depth > 1) else None
            try:
                score, pv = self._negamax(board, depth, -INFINITY, INFINITY, 0)
            except _Timeout:
                result.timed_out = True
                break
            elapsed = time.perf_counter() - start
            info = IterationInfo(depth, score, pv, self.stats.nodes, self.stats.cutoffs,
                                 self.stats.seldepth, elapsed)
            result.iterations.append(info)
            result.best_move, result.score, result.pv, result.depth = pv[0], score, pv, depth
            self._root_best = pv[0]
            if on_iteration:
                on_iteration(info)
            if mate_in(score) is not None and abs(mate_in(score)) * 2 <= depth:
                break  # a forced mate was found within this depth: deeper can't do better
            if time_limit and elapsed > time_limit * 0.5:
                break  # the next depth takes several times longer: don't start it

        result.seconds = time.perf_counter() - start
        return result

    # ---------------------------------------------------------- internals

    def _check_time(self) -> None:
        if (self._deadline is not None and self.stats.nodes % _TIME_CHECK_EVERY == 0
                and time.perf_counter() > self._deadline):
            raise _Timeout

    def _negamax(self, board: chess.Board, depth: int, alpha: int, beta: int,
                 ply: int) -> tuple[int, list[chess.Move]]:
        """Score of ``board`` for the side to move, and the best line from here."""
        self.stats.nodes += 1
        self.stats.seldepth = max(self.stats.seldepth, ply)
        self._check_time()

        if ply > 0 and is_draw(board):
            return 0, []
        if depth <= 0:
            if self.quiescence:
                return self._quiesce(board, alpha, beta, ply), []
            if board.is_checkmate():  # same leaf rule as classic.white_eval
                return -MATE_SCORE + ply, []
            return evaluate(board), []

        moves = list(board.legal_moves)
        if not moves:
            return (-MATE_SCORE + ply if board.is_check() else 0), []
        if ply == 0 and self._root_best in moves:  # previous iteration's best move first
            moves.remove(self._root_best)
            moves.insert(0, self._root_best)

        best, best_pv = -INFINITY, []
        for move in moves:
            board.push(move)
            score, pv = self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            score = -score  # the opponent's good is our bad
            if score > best:
                best, best_pv = score, [move, *pv]
            if score > alpha:
                alpha = score
            if alpha >= beta:  # opponent would never allow this line
                self.stats.cutoffs += 1
                break
        return best, best_pv

    def _quiesce(self, board: chess.Board, alpha: int, beta: int, ply: int) -> int:
        """Search captures (and check evasions) until the position is quiet."""
        self.stats.nodes += 1
        self.stats.qnodes += 1
        self.stats.seldepth = max(self.stats.seldepth, ply)
        self._check_time()

        if ply >= MAX_PLY:
            return evaluate(board)
        in_check = board.is_check()
        if in_check:
            # In check, "doing nothing" is not an option: try every evasion.
            moves = list(board.legal_moves)
            if not moves:
                return -MATE_SCORE + ply
            best = -INFINITY
        else:
            # "Stand pat": we may decline all captures and keep the static score.
            best = evaluate(board)
            if best >= beta:
                return best
            alpha = max(alpha, best)
            moves = [m for m in board.legal_moves
                     if m.promotion or board.is_capture(m)]
            moves.sort(key=lambda m: mvv_lva(board, m), reverse=True)

        for move in moves:
            board.push(move)
            score = -self._quiesce(board, -beta, -alpha, ply + 1)
            board.pop()
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                self.stats.cutoffs += 1
                break
        return best
