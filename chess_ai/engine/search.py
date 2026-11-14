"""The engine's search: how the AI actually picks its move.

It is the same minimax with alpha-beta as ``classic.py``, written in the shorter
**negamax** form. Instead of separate "max" and "min" branches, every score is from the
side to move's point of view and is negated when passed up the tree, because
``max(a, b) == -min(-a, -b)``. Tests check it returns exactly the textbook scores.

Alpha-beta prunes the most when the **best move is searched first**, so most of the
techniques below are about ordering moves well or skipping hopeless ones. Each can be
switched off in :class:`SearchConfig` (the report measures what each one adds):

=====================  ===========================================================
quiescence             at the end of the depth, keep searching captures until the
                       position is quiet (fixes the "horizon effect")
move_ordering          try the transposition-table move, then captures (most
                       valuable victim first), killer moves, then history scores
transposition_table    remember positions already searched (positions are often
                       reached by different move orders, i.e. "transpositions")
pvs                    principal variation search: search the first move with the
                       full window, the rest with a cheap "null window" that only
                       proves they are worse (re-search if one is not)
null_move              "if I pass and I am *still* winning, this position is too
                       good: the opponent won't allow it" (big cut, not in check)
late_move_reductions   moves late in the ordered list are probably bad: search
                       them less deep first, full depth only if they surprise
futility               near the leaves, skip quiet moves that cannot possibly
                       raise the score enough to matter
check_extension        search one ply deeper when in check (forcing lines)
aspiration             start each depth with a narrow window around the last score
=====================  ===========================================================

Iterative deepening (depth 1, 2, 3... until time runs out) is always on.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace

from chess_ai import chess

from chess_ai.engine.classic import INFINITY, MATE_SCORE
from chess_ai.engine.evaluation import evaluate
from chess_ai.engine.tables import MG_VALUE

MAX_PLY = 128
MATE_THRESHOLD = MATE_SCORE - MAX_PLY  # scores beyond this are "mate in N"
_TIME_CHECK_EVERY = 1024  # nodes between clock checks

# Transposition-table entry flags: what the stored score means.
EXACT, LOWER, UPPER = 0, 1, 2  # exact / at least (failed high) / at most (failed low)

# Move-ordering scores (higher = searched earlier).
_TT_MOVE = 10_000_000
_CAPTURE = 1_000_000
_KILLER_1 = 900_000
_KILLER_2 = 800_000
_HISTORY_MAX = 700_000

ASPIRATION_WINDOW = 50  # centipawns either side of the previous score
FUTILITY_MARGIN = 200  # depth-1 futility pruning
REVERSE_FUTILITY_MARGIN = 120  # per ply, "static null move" pruning
DELTA_MARGIN = 200  # quiescence delta pruning


class _Timeout(Exception):
    """Raised inside the search when the time limit is reached."""


# ----------------------------------------------------------------------- config


@dataclass(frozen=True)
class SearchConfig:
    quiescence: bool = True
    move_ordering: bool = True
    transposition_table: bool = True
    pvs: bool = True
    null_move: bool = True
    late_move_reductions: bool = True
    futility: bool = True
    check_extension: bool = True
    aspiration: bool = True
    tt_max_entries: int = 2_000_000

    @classmethod
    def textbook(cls) -> SearchConfig:
        """Plain negamax alpha-beta: returns exactly the same scores as classic minimax."""
        return cls(**{f.name: False for f in fields(cls) if f.type in (bool, "bool")})

    @classmethod
    def phase3(cls) -> SearchConfig:
        """Alpha-beta + quiescence only (the Phase 3 engine, used as a baseline)."""
        return replace(cls.textbook(), quiescence=True)


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
    seldepth: int = 0  # deepest ply reached, including quiescence and extensions
    tt_hits: int = 0  # positions found in the transposition table
    tt_cutoffs: int = 0  # ...whose stored result answered the question outright
    null_cutoffs: int = 0
    reductions: int = 0  # late-move reductions applied
    researches: int = 0  # PVS / LMR / aspiration re-searches
    futility_prunes: int = 0

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


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


@dataclass(frozen=True)
class RootMoveStat:
    """What happened to one root move in the last completed iteration.

    With alpha-beta only the best move gets an exact score. The others are
    *proven worse*: the search stops as soon as it finds an opponent reply
    (the ``refutation``) showing the move is no better than the best so far.
    """

    move: chess.Move
    order: int  # position in the move ordering (0 = searched first)
    score: int  # side to move's point of view; a bound unless ``bound == "exact"``
    bound: str  # "exact", "upper" (score is at most this) or "lower" (at least this)
    nodes: int  # positions searched for this move
    refutation: chess.Move | None  # opponent reply that cut the move off, if known
    reduced: bool  # searched with a late-move reduction first
    researched: bool  # needed a second search (PVS / LMR re-search)

    def to_dict(self) -> dict:
        return {
            "move": self.move.uci(), "order": self.order, "score": self.score,
            "score_text": format_score(self.score), "bound": self.bound,
            "nodes": self.nodes,
            "refutation": self.refutation.uci() if self.refutation else None,
            "reduced": self.reduced, "researched": self.researched,
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
    root_moves: list[RootMoveStat] = field(default_factory=list)  # last completed depth

    @property
    def mate_in(self) -> int | None:
        return mate_in(self.score)

    @property
    def score_text(self) -> str:
        return format_score(self.score)


# ----------------------------------------------------------------------- helpers


def mvv_lva(board: chess.Board, move: chess.Move) -> int:
    """'Most Valuable Victim, Least Valuable Attacker': try PxQ first, QxP last."""
    if board.is_en_passant(move):
        victim = chess.PAWN
    else:
        victim = board.piece_type_at(move.to_square) or 0
    attacker = board.piece_type_at(move.from_square) or chess.PAWN
    score = (MG_VALUE[victim] if victim else 0) * 10 - MG_VALUE[attacker] // 10
    if move.promotion:
        score += MG_VALUE[move.promotion] * 10
    return score


def _position_key(board: chess.Board):
    """Hashable identity of a position (pieces, side to move, castling, en passant):
    a tuple of the board's bitboards. Python hashes it quickly, so it plays the role of
    a Zobrist hash (which would be slower to update move by move in pure Python)."""
    return board.position_key()


def _has_non_pawn_material(board: chess.Board, color: chess.Color) -> bool:
    return bool(board.occupied_co[color] & ~(board.pawns | board.kings))


def _insufficient_material(board: chess.Board) -> bool:
    """Fast check for the common dead draws: K v K, K+N v K, K+B v K."""
    return not (board.pawns | board.rooks | board.queens) and \
        chess.popcount(board.occupied) <= 3


def _to_tt(score: int, ply: int) -> int:
    """Mate scores depend on the distance from the root; store them relative to the
    stored position instead, so they stay right when reused."""
    if score >= MATE_THRESHOLD:
        return score + ply
    if score <= -MATE_THRESHOLD:
        return score - ply
    return score


def _from_tt(score: int, ply: int) -> int:
    if score >= MATE_THRESHOLD:
        return score - ply
    if score <= -MATE_THRESHOLD:
        return score + ply
    return score


# ----------------------------------------------------------------------- search


class Searcher:
    """Negamax alpha-beta search with iterative deepening and the techniques above.

    >>> result = Searcher().search(chess.Board(), time_limit=2.0)
    >>> result.best_move, result.score_text

    ``Searcher(SearchConfig.textbook())`` or ``Searcher(quiescence=False, ...)`` turn
    individual techniques off. The transposition table is kept between searches
    (call :meth:`new_game` to clear it).
    """

    def __init__(self, config: SearchConfig | None = None, **overrides) -> None:
        self.config = replace(config or SearchConfig(), **overrides)
        self.stats = SearchStats()
        self._tt: dict = {}
        self._history = [[0] * 4096 for _ in range(2)]  # [color][from*64 + to]
        self._killers: list[list[chess.Move | None]] = [[None, None] for _ in range(MAX_PLY + 2)]
        self._pv: list[list[chess.Move]] = [[] for _ in range(MAX_PLY + 2)]
        self._path: list = []  # position keys from the last irreversible move to here
        self._deadline: float | None = None
        self._root_best: chess.Move | None = None
        self._root_moves: list[RootMoveStat] = []  # filled during each root search
        self._refutation: chess.Move | None = None  # set by ply-1 cutoffs

    def new_game(self) -> None:
        self._tt.clear()
        self._history = [[0] * 4096 for _ in range(2)]

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
        cfg = self.config

        board = board.copy()  # never touch the caller's board
        self.stats = SearchStats()
        self._root_best = None
        self._killers = [[None, None] for _ in range(MAX_PLY + 2)]
        for side in self._history:  # keep some history from the last move, but fade it
            for i, v in enumerate(side):
                if v:
                    side[i] = v // 4
        if len(self._tt) > cfg.tt_max_entries:
            self._tt.clear()
        self._path = self._game_history_keys(board)
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
                score = self._search_root(board, depth, result.score)
            except _Timeout:
                result.timed_out = True
                break
            pv = list(self._pv[0])
            if not pv:  # can only happen if every move scored -INFINITY (never in practice)
                pv = [legal[0]]
            elapsed = time.perf_counter() - start
            info = IterationInfo(depth, score, pv, self.stats.nodes, self.stats.cutoffs,
                                 self.stats.seldepth, elapsed)
            result.iterations.append(info)
            result.best_move, result.score, result.pv, result.depth = pv[0], score, pv, depth
            result.root_moves = list(self._root_moves)
            self._root_best = pv[0]
            if on_iteration:
                on_iteration(info)
            if mate_in(score) is not None and abs(mate_in(score)) * 2 <= depth:
                break  # a forced mate was found within this depth: deeper can't do better
            if time_limit and elapsed > time_limit * 0.5:
                break  # the next depth takes several times longer: don't start it

        result.seconds = time.perf_counter() - start
        return result

    # ---------------------------------------------------------- root

    def _search_root(self, board: chess.Board, depth: int, previous: int) -> int:
        """One iteration. With aspiration windows, first try a narrow window around the
        previous score; if the true score falls outside it, search again wider."""
        if not self.config.aspiration or depth < 4 or abs(previous) >= MATE_THRESHOLD:
            return self._negamax(board, depth, -INFINITY, INFINITY, 0, True)
        alpha, beta = previous - ASPIRATION_WINDOW, previous + ASPIRATION_WINDOW
        while True:
            score = self._negamax(board, depth, alpha, beta, 0, True)
            if score <= alpha:
                alpha = -INFINITY
            elif score >= beta:
                beta = INFINITY
            else:
                return score
            self.stats.researches += 1

    def _game_history_keys(self, board: chess.Board) -> list:
        """Keys of the positions before the root since the last capture / pawn move,
        so the search recognises repetitions of positions from the actual game."""
        keys = []
        b = board.copy()
        for _ in range(min(board.halfmove_clock, len(board.move_stack))):
            b.pop()
            keys.append(_position_key(b))
        keys.reverse()
        return keys

    # ---------------------------------------------------------- move ordering

    def _order_moves(self, board: chess.Board, moves: list[chess.Move],
                     tt_move: chess.Move | None, ply: int) -> list[chess.Move]:
        if not self.config.move_ordering:
            first = tt_move or (self._root_best if ply == 0 else None)
            if first in moves:
                moves.remove(first)
                moves.insert(0, first)
            return moves
        killer1, killer2 = self._killers[ply]
        history = self._history[board.turn]
        scored = []
        for m in moves:
            if m == tt_move:
                s = _TT_MOVE
            elif m.promotion or board.is_capture(m):
                s = _CAPTURE + mvv_lva(board, m)
            elif m == killer1:
                s = _KILLER_1
            elif m == killer2:
                s = _KILLER_2
            else:
                s = history[m.from_square * 64 + m.to_square]
            scored.append((s, m))
        scored.sort(key=lambda sm: sm[0], reverse=True)
        return [m for _, m in scored]

    def _record_quiet_cutoff(self, board: chess.Board, move: chess.Move, depth: int,
                             ply: int) -> None:
        """A quiet move refuted the opponent: remember it for sibling positions."""
        killers = self._killers[ply]
        if killers[0] != move:
            killers[1], killers[0] = killers[0], move
        history = self._history[board.turn]
        idx = move.from_square * 64 + move.to_square
        history[idx] = min(history[idx] + depth * depth, _HISTORY_MAX - 1)

    # ---------------------------------------------------------- main search

    def _check_time(self) -> None:
        if (self._deadline is not None and self.stats.nodes % _TIME_CHECK_EVERY == 0
                and time.perf_counter() > self._deadline):
            raise _Timeout

    def _negamax(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int,
                 allow_null: bool) -> int:
        """Score of ``board`` for the side to move. Fills ``self._pv[ply]``."""
        cfg, stats = self.config, self.stats
        stats.nodes += 1
        if ply > stats.seldepth:
            stats.seldepth = ply
        self._check_time()
        self._pv[ply] = []
        is_pv = beta - alpha > 1  # full-window node (on the expected best line)
        key = _position_key(board)

        # --- draws: 50 moves, dead material, repetition (once is enough inside a search)
        if ply > 0:
            hm = board.halfmove_clock
            if hm >= 100 or _insufficient_material(board):
                return 0
            if hm >= 4 and key in self._path[-hm:]:
                return 0
        if ply >= MAX_PLY:
            return evaluate(board)

        in_check = board.is_check()
        if in_check and cfg.check_extension:
            depth += 1

        if depth <= 0:
            if cfg.quiescence:
                return self._quiesce(board, alpha, beta, ply)
            if board.is_checkmate():  # same leaf rule as classic.white_eval
                return -MATE_SCORE + ply
            return evaluate(board)

        # --- transposition table
        tt_move = None
        if cfg.transposition_table:
            entry = self._tt.get(key)
            if entry is not None:
                stats.tt_hits += 1
                e_depth, e_score, e_flag, tt_move = entry
                if e_depth >= depth and ply > 0 and not is_pv:
                    e_score = _from_tt(e_score, ply)
                    if (e_flag == EXACT or (e_flag == LOWER and e_score >= beta)
                            or (e_flag == UPPER and e_score <= alpha)):
                        stats.tt_cutoffs += 1
                        if ply == 1 and e_flag != UPPER:
                            self._refutation = tt_move  # the stored reply refutes it
                        return e_score

        # --- pruning before searching any move (never on the main line or in check)
        static_eval = None
        if not in_check and not is_pv and (cfg.futility or cfg.null_move):
            static_eval = evaluate(board)
            if (cfg.futility and depth <= 3 and abs(beta) < MATE_THRESHOLD
                    and static_eval - REVERSE_FUTILITY_MARGIN * depth >= beta):
                stats.futility_prunes += 1
                return static_eval
            if (cfg.null_move and allow_null and depth >= 3 and static_eval >= beta
                    and _has_non_pawn_material(board, board.turn)):
                r = 3 if depth >= 6 else 2
                board.push(chess.Move.null())
                self._path.append(None)
                score = -self._negamax(board, depth - 1 - r, -beta, -beta + 1, ply + 1, False)
                self._path.pop()
                board.pop()
                if score >= beta:
                    stats.null_cutoffs += 1
                    return beta if score >= MATE_THRESHOLD else score

        moves = list(board.legal_moves)
        if not moves:
            return -MATE_SCORE + ply if in_check else 0
        moves = self._order_moves(board, moves, tt_move, ply)

        futile = (cfg.futility and depth == 1 and static_eval is not None
                  and static_eval + FUTILITY_MARGIN <= alpha)
        killers = self._killers[ply]

        best, best_move, original_alpha = -INFINITY, None, alpha
        root = ply == 0
        if root:
            self._root_moves = []
        self._path.append(key)
        for i, move in enumerate(moves):
            quiet = not move.promotion and not board.is_capture(move)
            if futile and quiet and i > 0 and not board.gives_check(move):
                stats.futility_prunes += 1
                continue

            if root:  # record what alpha-beta does with each root move
                nodes_before, alpha_before = stats.nodes, alpha
                self._refutation = None
            reduction, researched = 0, False
            board.push(move)
            if i == 0 or not cfg.pvs:
                score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, True)
            else:
                if (cfg.late_move_reductions and depth >= 3 and i >= 3 and quiet
                        and not in_check and move not in killers and not board.is_check()):
                    reduction = 1 if i < 6 else 2
                    stats.reductions += 1
                score = -self._negamax(board, depth - 1 - reduction, -alpha - 1, -alpha,
                                       ply + 1, True)
                if score > alpha and reduction:  # reduced move surprised us: full depth
                    stats.researches += 1
                    researched = True
                    score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, ply + 1, True)
                if alpha < score < beta:  # better than expected: get its exact score
                    stats.researches += 1
                    researched = True
                    score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, True)
            board.pop()
            if root:
                bound = ("upper" if score <= alpha_before else
                         "lower" if score >= beta else "exact")
                self._root_moves.append(RootMoveStat(
                    move=move, order=i, score=score, bound=bound,
                    nodes=stats.nodes - nodes_before,
                    refutation=self._refutation if bound == "upper" else None,
                    reduced=bool(reduction), researched=researched,
                ))

            if score > best:
                best, best_move = score, move
                if score > alpha:
                    alpha = score
                    self._pv[ply] = [move, *self._pv[ply + 1]]
                    if alpha >= beta:  # the opponent would never allow this line
                        stats.cutoffs += 1
                        if ply == 1:
                            self._refutation = move  # this reply refutes the root move
                        if quiet and cfg.move_ordering:
                            self._record_quiet_cutoff(board, move, depth, ply)
                        break
        self._path.pop()

        if best_move is None:  # every move was futility-pruned: fall back on static eval
            return static_eval if static_eval is not None else alpha

        if cfg.transposition_table:
            old = self._tt.get(key)
            if old is None or depth >= old[0]:  # keep the deeper (more reliable) result
                flag = UPPER if best <= original_alpha else LOWER if best >= beta else EXACT
                self._tt[key] = (depth, _to_tt(best, ply), flag, best_move)
        return best

    # ---------------------------------------------------------- quiescence

    def _quiesce(self, board: chess.Board, alpha: int, beta: int, ply: int) -> int:
        """Search captures (and check evasions) until the position is quiet."""
        stats = self.stats
        stats.nodes += 1
        stats.qnodes += 1
        if ply > stats.seldepth:
            stats.seldepth = ply
        self._check_time()
        self._pv[ply] = []

        if ply >= MAX_PLY:
            return evaluate(board)
        in_check = board.is_check()
        if in_check:
            # In check, "doing nothing" is not an option: try every evasion.
            moves = list(board.legal_moves)
            if not moves:
                return -MATE_SCORE + ply
            stand_pat = best = -INFINITY
        else:
            # "Stand pat": we may decline all captures and keep the static score.
            stand_pat = best = evaluate(board)
            if best >= beta:
                return best
            if best > alpha:
                alpha = best
            moves = list(board.generate_legal_captures())
            # Quiet promotions too, but only generate moves for pawns about to promote.
            about_to_promote = board.pawns & board.occupied_co[board.turn] & (
                chess.BB_RANK_7 if board.turn == chess.WHITE else chess.BB_RANK_2)
            if about_to_promote:
                moves += [m for m in board.generate_legal_moves(about_to_promote)
                          if m.promotion and not board.is_capture(m)]
            moves.sort(key=lambda m: mvv_lva(board, m), reverse=True)

        delta = self.config.futility and not in_check
        for move in moves:
            if delta and not move.promotion:
                victim = chess.PAWN if board.is_en_passant(move) else \
                    board.piece_type_at(move.to_square)
                if stand_pat + MG_VALUE[victim] + DELTA_MARGIN <= alpha:
                    continue  # even winning this piece for free can't raise alpha
            board.push(move)
            score = -self._quiesce(board, -beta, -alpha, ply + 1)
            board.pop()
            if score > best:
                best = score
                if score > alpha:
                    alpha = score
                    if alpha >= beta:
                        stats.cutoffs += 1
                        break
        return best
