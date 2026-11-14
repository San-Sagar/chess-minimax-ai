"""Textbook minimax and alpha-beta, written to be read.

These are the two algorithms in the project title, written the way a textbook does:
White is the **maximising** player and Black the **minimising** player, and every score
is from White's point of view.

They are used to:

* teach / show the algorithm (Learn page, project report)
* **verify** the fast engine in ``search.py``: at the same depth, minimax,
  alpha-beta and the engine's negamax must all return exactly the same score.
  Alpha-beta only skips work; it never changes the answer.
* measure how much alpha-beta saves (``nodes`` counts every position visited)

They have no time limit, quiescence search or move ordering, so they are slow.
Use ``chess_ai.engine.search.Searcher`` to actually play.
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_ai import chess

from chess_ai.engine.evaluation import evaluate

MATE_SCORE = 100_000  # checkmate; mate in fewer moves scores higher (MATE_SCORE - ply)
INFINITY = 1_000_000


@dataclass
class ClassicResult:
    score: int  # centipawns, White's point of view
    best_move: chess.Move | None
    nodes: int = 0  # positions visited
    cutoffs: int = 0  # alpha-beta only: times the rest of a move list was skipped


def is_draw(board: chess.Board) -> bool:
    """Draw rules checked inside the search. A position repeated once is already scored
    as a draw: if repeating was good once, it can be repeated again (standard trick)."""
    return (board.is_insufficient_material() or board.halfmove_clock >= 100
            or board.is_repetition(2))


def white_eval(board: chess.Board, ply: int) -> int:
    """Score of a leaf position from White's point of view.

    A checkmate is recognised even at the leaf (cheap: ``is_checkmate`` only looks for
    legal moves when the side to move is in check), so a mate in 1 is found at depth 1.
    """
    if board.is_checkmate():
        return -MATE_SCORE + ply if board.turn == chess.WHITE else MATE_SCORE - ply
    score = evaluate(board)
    return score if board.turn == chess.WHITE else -score


# ----------------------------------------------------------------------- minimax


def minimax(board: chess.Board, depth: int) -> ClassicResult:
    """Plain minimax: look at **every** move sequence ``depth`` plies deep."""
    result = ClassicResult(score=0, best_move=None)
    result.score, result.best_move = _minimax(board.copy(), depth, 0, result)
    return result


def _minimax(board: chess.Board, depth: int, ply: int, stats: ClassicResult):
    stats.nodes += 1
    maximizing = board.turn == chess.WHITE

    if ply > 0 and is_draw(board):
        return 0, None
    if depth == 0:
        return white_eval(board, ply), None
    moves = list(board.legal_moves)
    if not moves:  # no legal moves: checkmate or stalemate
        if board.is_check():
            return (-MATE_SCORE + ply if maximizing else MATE_SCORE - ply), None
        return 0, None

    best_move = None
    if maximizing:  # White picks the move with the HIGHEST score
        best = -INFINITY
        for move in moves:
            board.push(move)
            score, _ = _minimax(board, depth - 1, ply + 1, stats)
            board.pop()
            if score > best:
                best, best_move = score, move
    else:  # Black picks the move with the LOWEST score
        best = INFINITY
        for move in moves:
            board.push(move)
            score, _ = _minimax(board, depth - 1, ply + 1, stats)
            board.pop()
            if score < best:
                best, best_move = score, move
    return best, best_move


# ----------------------------------------------------------------------- alpha-beta


def alphabeta(board: chess.Board, depth: int) -> ClassicResult:
    """Minimax with alpha-beta pruning: same answer, far fewer positions.

    * **alpha** = the best score White is already guaranteed elsewhere in the tree
    * **beta**  = the best score Black is already guaranteed elsewhere in the tree

    As soon as a position is shown to be worse for the side to move than an option
    it already has (``alpha >= beta``), its remaining moves cannot change the result
    and are skipped. That skip is a **cutoff**.
    """
    result = ClassicResult(score=0, best_move=None)
    result.score, result.best_move = _alphabeta(
        board.copy(), depth, -INFINITY, INFINITY, 0, result
    )
    return result


def _alphabeta(board: chess.Board, depth: int, alpha: int, beta: int, ply: int,
               stats: ClassicResult):
    stats.nodes += 1
    maximizing = board.turn == chess.WHITE

    if ply > 0 and is_draw(board):
        return 0, None
    if depth == 0:
        return white_eval(board, ply), None
    moves = list(board.legal_moves)
    if not moves:
        if board.is_check():
            return (-MATE_SCORE + ply if maximizing else MATE_SCORE - ply), None
        return 0, None

    best_move = None
    if maximizing:
        best = -INFINITY
        for move in moves:
            board.push(move)
            score, _ = _alphabeta(board, depth - 1, alpha, beta, ply + 1, stats)
            board.pop()
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, best)
            if alpha >= beta:  # Black already has a better option: Black won't allow this
                stats.cutoffs += 1
                break
    else:
        best = INFINITY
        for move in moves:
            board.push(move)
            score, _ = _alphabeta(board, depth - 1, alpha, beta, ply + 1, stats)
            board.pop()
            if score < best:
                best, best_move = score, move
            beta = min(beta, best)
            if alpha >= beta:  # White already has a better option: White won't allow this
                stats.cutoffs += 1
                break
    return best, best_move
