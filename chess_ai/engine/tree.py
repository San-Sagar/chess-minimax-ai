"""Record a small alpha-beta search tree for the search tree viewer.

The real search visits tens of thousands of positions, far too many to draw. This
module runs a *small* version of the same algorithm so you can see every step:

* only the ``breadth`` most promising moves at each node, ``depth`` plies deep
* the root is a **MAX** node (the AI picks the highest score), the next level **MIN**
  (the opponent picks the lowest), and so on; all values are from the AI's point of view
* every node stores the **alpha** and **beta** it was searched with, its value, and
  whether its parent was **cut off** after it; the moves skipped by a cutoff are kept
  as ``pruned`` nodes so the viewer can draw them greyed out
* leaf values come from quiescence search (the evaluation after captures settle)

With ``alpha_beta=False`` the same tree is searched by plain minimax (nothing
pruned), which shows how much work alpha-beta skipped *and* proves it found the same
value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chess_ai import chess

from chess_ai.engine.classic import INFINITY, MATE_SCORE
from chess_ai.engine.evaluation import evaluate
from chess_ai.engine.search import SearchConfig, Searcher, format_score, mvv_lva


@dataclass
class TreeNode:
    id: int
    move: str | None  # UCI of the move leading here (None at the root)
    san: str | None
    ply: int
    player: str  # "max" (AI to move) or "min" (opponent to move)
    status: str = "searched"  # "searched" or "pruned" (skipped by a cutoff)
    alpha: int | None = None  # window this node was searched with
    beta: int | None = None
    value: int | None = None  # AI's point of view
    is_leaf: bool = False
    caused_cutoff: bool = False  # after this child, the parent stopped searching
    best_child: int | None = None
    children: list[TreeNode] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "move": self.move, "san": self.san, "ply": self.ply,
            "player": self.player, "status": self.status,
            "alpha": _clip(self.alpha), "beta": _clip(self.beta),
            "value": self.value,
            "value_text": format_score(self.value) if self.value is not None else None,
            "is_leaf": self.is_leaf, "caused_cutoff": self.caused_cutoff,
            "best_child": self.best_child,
            "children": [c.to_dict() for c in self.children],
        }


def _clip(v: int | None):
    """JSON-friendly infinity."""
    if v is None:
        return None
    if v >= INFINITY:
        return "+inf"
    if v <= -INFINITY:
        return "-inf"
    return v


@dataclass
class SearchTree:
    root: TreeNode
    depth: int
    breadth: int
    alpha_beta: bool
    visited: int  # nodes actually searched
    pruned: int  # nodes skipped (counting whole skipped subtrees)
    best_move: str | None
    best_san: str | None
    value: int

    @property
    def total(self) -> int:
        return self.visited + self.pruned

    def to_dict(self) -> dict:
        return {
            "depth": self.depth, "breadth": self.breadth, "alpha_beta": self.alpha_beta,
            "visited": self.visited, "pruned": self.pruned, "total": self.total,
            "pruned_pct": round(100 * self.pruned / self.total, 1) if self.total else 0.0,
            "best_move": self.best_move, "best_san": self.best_san,
            "value": self.value, "value_text": format_score(self.value),
            "root": self.root.to_dict(),
        }


def _subtree_size(breadth: int, depth: int) -> int:
    """Nodes in a full ``breadth``-wide tree of ``depth`` plies below (and incl.) a node."""
    return sum(breadth ** i for i in range(depth + 1))


class _Recorder:
    def __init__(self, ai_color: chess.Color, depth: int, breadth: int, alpha_beta: bool):
        self.ai_color, self.depth, self.breadth, self.alpha_beta = (
            ai_color, depth, breadth, alpha_beta)
        self.next_id = 0
        self.visited = 0
        self.pruned = 0
        self._q = Searcher(SearchConfig.phase3())  # quiescence for leaf values

    def _new_id(self) -> int:
        self.next_id += 1
        return self.next_id - 1

    def _leaf_value(self, board: chess.Board, ply: int) -> int:
        """Leaf score from the AI's point of view."""
        if board.is_checkmate():
            score = -MATE_SCORE + ply  # side to move is mated
        elif board.is_stalemate() or board.is_insufficient_material():
            score = 0
        else:
            score = self._q._quiesce(board, -INFINITY, INFINITY, 0)
        return score if board.turn == self.ai_color else -score

    def _ordered_moves(self, board: chess.Board, pv_move: chess.Move | None) -> list[chess.Move]:
        """The ``breadth`` most promising moves, best first so alpha-beta cuts well:
        the engine's own choice (if on its line), then captures (most valuable victim
        first), then checks, then quiet moves by their 1-ply evaluation."""
        scored = []
        for m in board.legal_moves:
            if m == pv_move:
                s = 10_000_000
            elif m.promotion or board.is_capture(m):
                s = 5_000_000 + mvv_lva(board, m)
            else:
                check = board.gives_check(m)
                board.push(m)
                s = -evaluate(board) + (1_000_000 if check else 0)
                board.pop()
            scored.append((s, m))
        scored.sort(key=lambda sm: sm[0], reverse=True)
        return [m for _, m in scored[: self.breadth]]

    def search(self, board: chess.Board, node: TreeNode, depth: int, alpha: int,
               beta: int, pv: list[chess.Move] | None = None) -> int:
        self.visited += 1
        node.alpha, node.beta = alpha, beta
        maximizing = board.turn == self.ai_color

        if depth == 0 or board.is_game_over():
            node.is_leaf = True
            node.value = self._leaf_value(board, node.ply)
            return node.value

        pv_move = pv[0] if pv else None
        moves = self._ordered_moves(board, pv_move)
        best = -INFINITY if maximizing else INFINITY
        cut = False
        for move in moves:
            child = TreeNode(id=self._new_id(), move=move.uci(), san=board.san(move),
                             ply=node.ply + 1, player="min" if maximizing else "max")
            node.children.append(child)
            if cut:  # skipped by alpha-beta: keep it so the viewer can grey it out
                child.status = "pruned"
                self.pruned += _subtree_size(self.breadth, depth - 1)
                continue
            board.push(move)
            child_pv = pv[1:] if pv_move is not None and move == pv_move else None
            value = self.search(board, child, depth - 1, alpha, beta, child_pv)
            board.pop()
            if (maximizing and value > best) or (not maximizing and value < best):
                best, node.best_child = value, child.id
            if self.alpha_beta:
                if maximizing:
                    alpha = max(alpha, best)
                else:
                    beta = min(beta, best)
                if alpha >= beta:
                    child.caused_cutoff = True
                    cut = True
        node.value = best
        return best


def record_tree(board: chess.Board, depth: int = 3, breadth: int = 4,
                alpha_beta: bool = True, pv: list[chess.Move] | None = None) -> SearchTree:
    """Search ``board`` with a small alpha-beta (or plain minimax) and record the tree.

    ``pv``: the real engine's expected line. Its moves are always included (and tried
    first), so the tree shows the move the AI actually chose and why.
    """
    if depth < 1 or breadth < 1:
        raise ValueError("depth and breadth must be >= 1")
    board = board.copy()
    rec = _Recorder(board.turn, depth, breadth, alpha_beta)
    root = TreeNode(id=rec._new_id(), move=None, san=None, ply=0, player="max")
    value = rec.search(board, root, depth, -INFINITY, INFINITY, pv)
    best = next((c for c in root.children if c.id == root.best_child), None)
    return SearchTree(root=root, depth=depth, breadth=breadth, alpha_beta=alpha_beta,
                      visited=rec.visited, pruned=rec.pruned,
                      best_move=best.move if best else None,
                      best_san=best.san if best else None, value=value)
