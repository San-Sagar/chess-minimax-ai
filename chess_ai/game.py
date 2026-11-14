"""Game layer: one game of chess between a human and the AI.

This wraps our own rules engine's ``chess.Board`` (``chess_ai.chess``: board, legal
move generation, FEN, SAN) and adds what the rest of the project needs:

* a move history of :class:`MoveRecord` objects (who moved what, captures, checks...)
* making moves from UCI (``"e2e4"``), SAN (``"e4"``, ``"Nf3"``) or ``chess.Move``
* undoing moves (e.g. "take back my move and the AI's reply")
* game status: checkmate, stalemate, draws, resignation, agreed draw
* loading and saving positions and games (FEN / PGN)
* captured pieces and material balance for the UI

The engine (``chess_ai.engine``) searches on plain ``chess.Board`` objects for speed;
this class is for the game being played, the server and the UI.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass

from chess_ai import chess

WHITE = "white"
BLACK = "black"

PIECE_VALUES = {  # simple material values used for the "+3" style balance in the UI
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

# Map rule-engine terminations to the names used by the API / UI.
_TERMINATION_NAMES = {
    chess.Termination.CHECKMATE: "checkmate",
    chess.Termination.STALEMATE: "stalemate",
    chess.Termination.INSUFFICIENT_MATERIAL: "insufficient_material",
    chess.Termination.SEVENTYFIVE_MOVES: "seventyfive_moves",
    chess.Termination.FIVEFOLD_REPETITION: "fivefold_repetition",
    chess.Termination.FIFTY_MOVES: "fifty_moves",
    chess.Termination.THREEFOLD_REPETITION: "threefold_repetition",
}


class IllegalMoveError(ValueError):
    """Raised when a move is illegal, unparsable, or the game is already over."""


def color_name(color: chess.Color) -> str:
    return WHITE if color == chess.WHITE else BLACK


def _parse_color(color: str | chess.Color) -> chess.Color:
    if isinstance(color, bool):
        return color
    if color not in (WHITE, BLACK):
        raise ValueError(f"color must be 'white' or 'black', got {color!r}")
    return color == WHITE


@dataclass(frozen=True)
class MoveRecord:
    """One move in the game history, with everything the UI needs to display it."""

    ply: int  # 1 = White's first move, 2 = Black's first move, ...
    move_number: int  # the "1." in "1. e4 e5"
    color: str  # "white" or "black": who made the move
    san: str  # standard notation, e.g. "Nxf7+"
    uci: str  # e.g. "g5f7"
    piece: str  # moving piece type: "P", "N", "B", "R", "Q", "K"
    from_square: str  # e.g. "g5"
    to_square: str  # e.g. "f7"
    captured: str | None  # captured piece type, e.g. "P", or None
    promotion: str | None  # promoted-to piece type, e.g. "Q", or None
    is_check: bool
    is_checkmate: bool
    castling: str | None  # "kingside", "queenside" or None
    is_en_passant: bool
    fen_after: str  # position after the move (lets the UI replay any point)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GameStatus:
    """Whether the game is over, why, and who won."""

    is_over: bool
    reason: str | None  # e.g. "checkmate", "stalemate", "resignation"; None while ongoing
    winner: str | None  # "white", "black", or None (ongoing or draw)
    result: str  # PGN result: "1-0", "0-1", "1/2-1/2" or "*"

    def to_dict(self) -> dict:
        return asdict(self)


ONGOING = GameStatus(is_over=False, reason=None, winner=None, result="*")


class Game:
    """A chess game with a move history. Draws by repetition / 50 moves end the game
    automatically (like on most online sites), so the AI and the UI never have to
    handle a separate 'claim draw' step."""

    def __init__(self, fen: str = chess.STARTING_FEN) -> None:
        try:
            self._board = chess.Board(fen)
        except ValueError as exc:
            raise ValueError(f"invalid FEN: {fen!r} ({exc})") from exc
        if not self._board.is_valid():
            raise ValueError(f"illegal position in FEN: {fen!r} ({self._board.status()!r})")
        self.start_fen = self._board.fen()
        self._history: list[MoveRecord] = []
        self._manual_end: GameStatus | None = None  # resignation / agreed draw

    # ------------------------------------------------------------------ state

    @property
    def board(self) -> chess.Board:
        """A copy of the current board (safe to hand to the engine)."""
        return self._board.copy()

    @property
    def fen(self) -> str:
        return self._board.fen()

    @property
    def turn(self) -> str:
        return color_name(self._board.turn)

    @property
    def history(self) -> list[MoveRecord]:
        return list(self._history)

    @property
    def is_check(self) -> bool:
        return self._board.is_check()

    @property
    def last_move(self) -> MoveRecord | None:
        return self._history[-1] if self._history else None

    def status(self) -> GameStatus:
        if self._manual_end is not None:
            return self._manual_end
        board = self._board
        # Checkmate, stalemate, insufficient material, 75-move and fivefold rules.
        outcome = board.outcome(claim_draw=False)
        if outcome is None:
            # Claimable draws are applied automatically, but only once they have actually
            # happened. (A "can claim" rule would also count a draw that one more
            # move *would* reach, which would end the game a move too early.)
            if board.is_repetition(3):
                return GameStatus(True, "threefold_repetition", None, "1/2-1/2")
            if board.halfmove_clock >= 100:
                return GameStatus(True, "fifty_moves", None, "1/2-1/2")
            return ONGOING
        return GameStatus(
            is_over=True,
            reason=_TERMINATION_NAMES.get(outcome.termination, outcome.termination.name.lower()),
            winner=None if outcome.winner is None else color_name(outcome.winner),
            result=outcome.result(),
        )

    @property
    def is_over(self) -> bool:
        return self.status().is_over

    # ------------------------------------------------------------------ legal moves

    def legal_moves(self) -> list[str]:
        """All legal moves in UCI notation."""
        return [m.uci() for m in self._board.legal_moves]

    def legal_moves_by_square(self) -> dict[str, list[str]]:
        """{from_square: [to_squares]}: what the UI needs to draw legal-move dots."""
        dests: dict[str, list[str]] = {}
        for m in self._board.legal_moves:
            to = chess.square_name(m.to_square)
            targets = dests.setdefault(chess.square_name(m.from_square), [])
            if to not in targets:  # promotions give 4 moves to the same square
                targets.append(to)
        return dests

    def needs_promotion(self, from_square: str, to_square: str) -> bool:
        """True if moving from -> to is a pawn promotion (the UI shows a piece picker)."""
        frm, to = chess.parse_square(from_square), chess.parse_square(to_square)
        return any(
            m.from_square == frm and m.to_square == to and m.promotion
            for m in self._board.legal_moves
        )

    # ------------------------------------------------------------------ moves

    def parse_move(self, move: str | chess.Move) -> chess.Move:
        """Turn UCI / SAN / chess.Move into a legal chess.Move, or raise IllegalMoveError."""
        if isinstance(move, chess.Move):
            parsed = move
        else:
            text = move.strip()
            try:
                parsed = chess.Move.from_uci(text)
            except ValueError:
                try:
                    parsed = self._board.parse_san(text)
                except ValueError as exc:
                    raise IllegalMoveError(f"illegal or unparsable move: {move!r}") from exc
        if parsed not in self._board.legal_moves:
            raise IllegalMoveError(f"illegal move in this position: {parsed.uci()!r}")
        return parsed

    def make_move(self, move: str | chess.Move) -> MoveRecord:
        """Play a move and return its history record."""
        if self.is_over:
            raise IllegalMoveError("the game is over")
        m = self.parse_move(move)
        board = self._board

        piece = board.piece_at(m.from_square)
        assert piece is not None  # guaranteed by legality
        is_ep = board.is_en_passant(m)
        if is_ep:
            captured: str | None = "P"
        else:
            cap = board.piece_at(m.to_square)
            captured = cap.symbol().upper() if cap and not board.is_castling(m) else None
        castling = None
        if board.is_kingside_castling(m):
            castling = "kingside"
        elif board.is_queenside_castling(m):
            castling = "queenside"

        san = board.san(m)
        mover = board.turn
        move_number = board.fullmove_number
        board.push(m)

        record = MoveRecord(
            ply=len(self._history) + 1,
            move_number=move_number,
            color=color_name(mover),
            san=san,
            uci=m.uci(),
            piece=piece.symbol().upper(),
            from_square=chess.square_name(m.from_square),
            to_square=chess.square_name(m.to_square),
            captured=captured,
            promotion=chess.piece_symbol(m.promotion).upper() if m.promotion else None,
            is_check=board.is_check(),
            is_checkmate=board.is_checkmate(),
            castling=castling,
            is_en_passant=is_ep,
            fen_after=board.fen(),
        )
        self._history.append(record)
        return record

    def undo(self, plies: int = 1) -> list[MoveRecord]:
        """Take back the last ``plies`` moves (2 = your move and the AI's reply).
        Also cancels a resignation / agreed draw. Returns the undone records."""
        if plies < 1:
            raise ValueError("plies must be >= 1")
        if plies > len(self._history):
            raise IllegalMoveError(f"cannot undo {plies} moves, only {len(self._history)} played")
        undone = []
        for _ in range(plies):
            self._board.pop()
            undone.append(self._history.pop())
        self._manual_end = None
        return undone

    # ------------------------------------------------------------------ manual endings

    def resign(self, color: str | chess.Color) -> GameStatus:
        if self.is_over:
            raise IllegalMoveError("the game is over")
        loser = _parse_color(color)
        self._manual_end = GameStatus(
            is_over=True,
            reason="resignation",
            winner=color_name(not loser),
            result="0-1" if loser == chess.WHITE else "1-0",
        )
        return self._manual_end

    def agree_draw(self) -> GameStatus:
        if self.is_over:
            raise IllegalMoveError("the game is over")
        self._manual_end = GameStatus(
            is_over=True, reason="draw_agreed", winner=None, result="1/2-1/2"
        )
        return self._manual_end

    # ------------------------------------------------------------------ captures

    def captured_pieces(self) -> dict[str, list[str]]:
        """Pieces each side has captured, e.g. {"white": ["P", "N"], "black": ["P"]}."""
        taken: dict[str, list[str]] = {WHITE: [], BLACK: []}
        for rec in self._history:
            if rec.captured:
                taken[rec.color].append(rec.captured)
        return taken

    def material_balance(self) -> int:
        """Material on the board, White minus Black, in pawns (e.g. +3 = White up a piece)."""
        total = 0
        for piece_type, value in PIECE_VALUES.items():
            total += value * chess.popcount(self._board.pieces_mask(piece_type, chess.WHITE))
            total -= value * chess.popcount(self._board.pieces_mask(piece_type, chess.BLACK))
        return total

    # ------------------------------------------------------------------ FEN / PGN

    @classmethod
    def from_fen(cls, fen: str) -> Game:
        return cls(fen)

    @classmethod
    def from_pgn(cls, pgn_text: str) -> Game:
        """Load a game from PGN text (main line only), replaying every move."""
        parsed = chess.pgn.read_pgn(pgn_text)  # raises ValueError for broken PGN
        game = cls(parsed.start_fen)
        for move in parsed.moves:
            game.make_move(move)
        return game

    def to_pgn(
        self,
        white: str = "Human",
        black: str = "Chess Minimax AI",
        event: str = "Human vs AI",
    ) -> str:
        """Export the game as PGN text (loadable in Lichess, chess.com, Arena...)."""
        status = self.status()
        headers = {
            "Event": event,
            "Site": "Chess Minimax AI",
            "Date": _dt.date.today().strftime("%Y.%m.%d"),
            "Round": "-",
            "White": white,
            "Black": black,
        }
        if status.reason:
            headers["Termination"] = status.reason
        moves = [chess.Move.from_uci(rec.uci) for rec in self._history]
        return chess.pgn.write_pgn(headers, moves, self.start_fen, status.result)

    # ------------------------------------------------------------------ serialisation

    def to_dict(self) -> dict:
        """Full game state for the API / UI."""
        return {
            "fen": self.fen,
            "start_fen": self.start_fen,
            "turn": self.turn,
            "is_check": self.is_check,
            "status": self.status().to_dict(),
            "history": [r.to_dict() for r in self._history],
            "legal_moves": self.legal_moves_by_square(),
            "captured": self.captured_pieces(),
            "material_balance": self.material_balance(),
        }
