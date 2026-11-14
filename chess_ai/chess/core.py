"""Chess rules written from scratch: board, attacks, legal moves, FEN, SAN, game end.

Design: **bitboards**. A bitboard is a 64-bit integer with one bit per square
(bit 0 = a1, bit 1 = b1, ..., bit 63 = h8). The board is stored as six bitboards,
one per piece type (pawns, knights, ...), plus one per colour. Questions like
"which squares does this rook attack?" become fast bit operations:

* knight / king / pawn attacks are looked up in tables computed once at start-up
* sliding pieces (bishop, rook, queen) use per-line lookup tables: for every square
  and every arrangement of blocking pieces on its rank (or file, or diagonal), the
  attacked squares are precomputed, so an attack is one dictionary lookup per line

Legal moves are generated without trial-and-error "make the move, see if the king is
in check": the generator knows which of our pieces are **pinned** (they may only move
along the pin line) and, when in check, only generates moves that capture the checker,
block the check, or move the king to a safe square. The perft tests prove the result
matches the published counts for the standard test positions exactly.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Iterator
from typing import NamedTuple

# ======================================================================= basics

Color = bool
Square = int
PieceType = int
Bitboard = int

WHITE: Color = True
BLACK: Color = False
COLORS = [WHITE, BLACK]
COLOR_NAMES = ["black", "white"]

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = range(1, 7)
PIECE_TYPES = [PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING]
PIECE_SYMBOLS = [None, "p", "n", "b", "r", "q", "k"]
PIECE_NAMES = [None, "pawn", "knight", "bishop", "rook", "queen", "king"]
UNICODE_PIECES = {"P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
                  "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚"}

FILE_NAMES = "abcdefgh"
RANK_NAMES = "12345678"
SQUARES = list(range(64))
SQUARE_NAMES = [f + r for r in RANK_NAMES for f in FILE_NAMES]
A1, B1, C1, D1, E1, F1, G1, H1 = range(8)
A8, B8, C8, D8, E8, F8, G8, H8 = range(56, 64)

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def piece_symbol(piece_type: PieceType) -> str:
    return PIECE_SYMBOLS[piece_type]


def square(file_index: int, rank_index: int) -> Square:
    return rank_index * 8 + file_index


def square_file(sq: Square) -> int:
    return sq & 7


def square_rank(sq: Square) -> int:
    return sq >> 3


def square_name(sq: Square) -> str:
    return SQUARE_NAMES[sq]


def parse_square(name: str) -> Square:
    return SQUARE_NAMES.index(name)


def square_mirror(sq: Square) -> Square:
    return sq ^ 56


# ======================================================================= bitboards

BB_EMPTY = 0
BB_ALL = 0xFFFF_FFFF_FFFF_FFFF
BB_SQUARES = [1 << s for s in SQUARES]
BB_FILES = [0x0101_0101_0101_0101 << f for f in range(8)]
BB_RANKS = [0xFF << (8 * r) for r in range(8)]
BB_FILE_A, BB_FILE_B, BB_FILE_C, BB_FILE_D, BB_FILE_E, BB_FILE_F, BB_FILE_G, BB_FILE_H = BB_FILES
BB_RANK_1, BB_RANK_2, BB_RANK_3, BB_RANK_4, BB_RANK_5, BB_RANK_6, BB_RANK_7, BB_RANK_8 = BB_RANKS
BB_DARK_SQUARES = 0xAA55_AA55_AA55_AA55
BB_LIGHT_SQUARES = ~BB_DARK_SQUARES & BB_ALL
BB_A1, BB_H1, BB_A8, BB_H8 = BB_SQUARES[A1], BB_SQUARES[H1], BB_SQUARES[A8], BB_SQUARES[H8]
BB_CORNERS = BB_A1 | BB_H1 | BB_A8 | BB_H8


def popcount(bb: Bitboard) -> int:
    return bb.bit_count()


def lsb(bb: Bitboard) -> Square:
    return (bb & -bb).bit_length() - 1


def msb(bb: Bitboard) -> Square:
    return bb.bit_length() - 1


def scan_forward(bb: Bitboard) -> Iterator[Square]:
    """Squares of the set bits, a1 first."""
    while bb:
        low = bb & -bb
        yield low.bit_length() - 1
        bb ^= low


def scan_reversed(bb: Bitboard) -> Iterator[Square]:
    while bb:
        sq = bb.bit_length() - 1
        yield sq
        bb ^= 1 << sq


def flip_vertical(bb: Bitboard) -> Bitboard:
    """Mirror a bitboard rank 1 <-> rank 8."""
    return int.from_bytes(bb.to_bytes(8, "big"), "little")


# ======================================================================= attack tables


def _step_attacks(sq: Square, steps: Iterable[tuple[int, int]]) -> Bitboard:
    f, r = square_file(sq), square_rank(sq)
    bb = 0
    for df, dr in steps:
        nf, nr = f + df, r + dr
        if 0 <= nf < 8 and 0 <= nr < 8:
            bb |= BB_SQUARES[square(nf, nr)]
    return bb


def _slide_attacks(sq: Square, occupied: Bitboard, directions) -> Bitboard:
    """Squares a slider on ``sq`` attacks, stopping at (and including) blockers."""
    f, r = square_file(sq), square_rank(sq)
    bb = 0
    for df, dr in directions:
        nf, nr = f + df, r + dr
        while 0 <= nf < 8 and 0 <= nr < 8:
            s = BB_SQUARES[square(nf, nr)]
            bb |= s
            if occupied & s:
                break
            nf += df
            nr += dr
    return bb


KNIGHT_ATTACKS = [_step_attacks(s, [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1),
                                    (-2, 1), (-1, 2)]) for s in SQUARES]
KING_ATTACKS = [_step_attacks(s, [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1),
                                  (0, -1), (1, -1)]) for s in SQUARES]
BB_KNIGHT_ATTACKS = KNIGHT_ATTACKS
BB_KING_ATTACKS = KING_ATTACKS
# PAWN_ATTACKS[color][sq]: squares a pawn of ``color`` on ``sq`` attacks.
PAWN_ATTACKS = [
    [_step_attacks(s, [(-1, -1), (1, -1)]) for s in SQUARES],  # black
    [_step_attacks(s, [(-1, 1), (1, 1)]) for s in SQUARES],  # white
]

_LINES = {
    "rank": [(1, 0), (-1, 0)],
    "file": [(0, 1), (0, -1)],
    "diag": [(1, 1), (-1, -1)],
    "anti": [(1, -1), (-1, 1)],
}


def _line_tables(directions):
    """For every square: (mask of the line, {blockers on the line: attacks})."""
    masks, tables = [], []
    for sq in SQUARES:
        mask = _slide_attacks(sq, 0, directions)
        table = {}
        sub = 0
        while True:  # enumerate every subset of the mask ("carry-rippler" trick)
            table[sub] = _slide_attacks(sq, sub, directions)
            sub = (sub - mask) & mask
            if sub == 0:
                break
        masks.append(mask)
        tables.append(table)
    return masks, tables


_RANK_MASKS, _RANK_ATTACKS = _line_tables(_LINES["rank"])
_FILE_MASKS, _FILE_ATTACKS = _line_tables(_LINES["file"])
_DIAG_MASKS, _DIAG_ATTACKS = _line_tables(_LINES["diag"])
_ANTI_MASKS, _ANTI_ATTACKS = _line_tables(_LINES["anti"])


def rook_attacks(sq: Square, occupied: Bitboard) -> Bitboard:
    return (_RANK_ATTACKS[sq][occupied & _RANK_MASKS[sq]]
            | _FILE_ATTACKS[sq][occupied & _FILE_MASKS[sq]])


def bishop_attacks(sq: Square, occupied: Bitboard) -> Bitboard:
    return (_DIAG_ATTACKS[sq][occupied & _DIAG_MASKS[sq]]
            | _ANTI_ATTACKS[sq][occupied & _ANTI_MASKS[sq]])


def queen_attacks(sq: Square, occupied: Bitboard) -> Bitboard:
    return rook_attacks(sq, occupied) | bishop_attacks(sq, occupied)


def _lines_and_between():
    """RAYS[a][b]: the whole line through a and b (edge to edge) if they share a rank,
    file or diagonal, else 0. BETWEEN[a][b]: squares strictly between them."""
    rays = [[0] * 64 for _ in SQUARES]
    between = [[0] * 64 for _ in SQUARES]
    for a in SQUARES:
        for masks, directions in ((_RANK_MASKS, _LINES["rank"]), (_FILE_MASKS, _LINES["file"]),
                                  (_DIAG_MASKS, _LINES["diag"]), (_ANTI_MASKS, _LINES["anti"])):
            for b in scan_forward(masks[a]):
                rays[a][b] = masks[a] | BB_SQUARES[a]
                between[a][b] = (_slide_attacks(a, BB_SQUARES[b], directions)
                                 & _slide_attacks(b, BB_SQUARES[a], directions))
    return rays, between


RAYS, BETWEEN = _lines_and_between()


# ======================================================================= pieces & moves


class Piece(NamedTuple):
    piece_type: PieceType
    color: Color

    def symbol(self) -> str:
        s = PIECE_SYMBOLS[self.piece_type]
        return s.upper() if self.color == WHITE else s

    @classmethod
    def from_symbol(cls, symbol: str) -> Piece:
        return cls(PIECE_SYMBOLS.index(symbol.lower()), symbol.isupper())


class Move(NamedTuple):
    """A move: from-square, to-square and (for pawn promotions) the new piece type.
    Castling is written as the king's move (e1g1). The null move is a1a1 ("0000")."""

    from_square: Square
    to_square: Square
    promotion: PieceType | None = None

    def uci(self) -> str:
        if not self:
            return "0000"
        promo = PIECE_SYMBOLS[self.promotion] if self.promotion else ""
        return SQUARE_NAMES[self.from_square] + SQUARE_NAMES[self.to_square] + promo

    def __str__(self) -> str:
        return self.uci()

    def __repr__(self) -> str:
        return f"Move.from_uci({self.uci()!r})"

    def __bool__(self) -> bool:
        return self.from_square != self.to_square or self.promotion is not None

    @classmethod
    def from_uci(cls, text: str) -> Move:
        if text == "0000":
            return cls.null()
        if len(text) not in (4, 5):
            raise ValueError(f"invalid uci: {text!r}")
        try:
            frm, to = SQUARE_NAMES.index(text[:2]), SQUARE_NAMES.index(text[2:4])
            promo = PIECE_SYMBOLS.index(text[4]) if len(text) == 5 else None
        except ValueError:
            raise ValueError(f"invalid uci: {text!r}") from None
        if promo in (None, KNIGHT, BISHOP, ROOK, QUEEN) and frm != to:
            return cls(frm, to, promo)
        raise ValueError(f"invalid uci: {text!r}")

    @classmethod
    def null(cls) -> Move:
        return cls(0, 0, None)


class Termination(enum.Enum):
    CHECKMATE = enum.auto()
    STALEMATE = enum.auto()
    INSUFFICIENT_MATERIAL = enum.auto()
    SEVENTYFIVE_MOVES = enum.auto()
    FIVEFOLD_REPETITION = enum.auto()
    FIFTY_MOVES = enum.auto()
    THREEFOLD_REPETITION = enum.auto()


class Outcome(NamedTuple):
    termination: Termination
    winner: Color | None

    def result(self) -> str:
        return "1/2-1/2" if self.winner is None else ("1-0" if self.winner else "0-1")


class LegalMoves:
    """``board.legal_moves``: iterate, count, or test ``move in board.legal_moves``."""

    __slots__ = ("_board",)

    def __init__(self, board: Board) -> None:
        self._board = board

    def __iter__(self) -> Iterator[Move]:
        return self._board.generate_legal_moves()

    def __contains__(self, move) -> bool:
        return self._board.is_legal(move)

    def __bool__(self) -> bool:
        return any(True for _ in self._board.generate_legal_moves())

    def __len__(self) -> int:
        return self.count()

    def count(self) -> int:
        return sum(1 for _ in self._board.generate_legal_moves())


_PROMOTIONS = (QUEEN, ROOK, BISHOP, KNIGHT)


# ======================================================================= the board


class Board:
    """A chess position plus the moves that led to it (for undo and repetition)."""

    __slots__ = ("pawns", "knights", "bishops", "rooks", "queens", "kings", "occupied_co",
                 "occupied", "turn", "castling_rights", "ep_square", "halfmove_clock",
                 "fullmove_number", "move_stack", "_stack")

    def __init__(self, fen: str | None = STARTING_FEN) -> None:
        self.move_stack: list[Move] = []
        self._stack: list[tuple] = []
        if fen is None:
            self.clear()
        else:
            self.set_fen(fen)

    # ------------------------------------------------------------- setup

    def clear(self) -> None:
        self.pawns = self.knights = self.bishops = self.rooks = self.queens = self.kings = 0
        self.occupied_co = [0, 0]
        self.occupied = 0
        self.turn = WHITE
        self.castling_rights = 0
        self.ep_square: Square | None = None
        self.halfmove_clock = 0
        self.fullmove_number = 1
        self.move_stack = []
        self._stack = []

    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        if len(parts) == 4:
            parts += ["0", "1"]
        if len(parts) != 6:
            raise ValueError(f"FEN needs 6 fields: {fen!r}")
        placement, turn, castling, ep, halfmove, fullmove = parts
        rows = placement.split("/")
        if len(rows) != 8:
            raise ValueError(f"FEN board needs 8 ranks: {fen!r}")
        self.clear()
        for i, row in enumerate(rows):
            rank, file = 7 - i, 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                elif ch.lower() in "pnbrqk":
                    if file > 7:
                        raise ValueError(f"too many squares in rank: {fen!r}")
                    self._set_piece(square(file, rank), PIECE_SYMBOLS.index(ch.lower()),
                                    ch.isupper())
                    file += 1
                else:
                    raise ValueError(f"invalid FEN character {ch!r}: {fen!r}")
            if file != 8:
                raise ValueError(f"rank does not have 8 squares: {fen!r}")
        if turn not in ("w", "b"):
            raise ValueError(f"invalid side to move: {fen!r}")
        self.turn = turn == "w"
        rights = 0
        if castling != "-":
            for ch in castling:
                corner = {"K": BB_H1, "Q": BB_A1, "k": BB_H8, "q": BB_A8}.get(ch)
                if corner is None:
                    raise ValueError(f"invalid castling field: {fen!r}")
                rights |= corner
        self.castling_rights = rights
        self._clean_castling_rights()
        if ep == "-":
            self.ep_square = None
        else:
            if ep not in SQUARE_NAMES:
                raise ValueError(f"invalid en passant square: {fen!r}")
            self.ep_square = SQUARE_NAMES.index(ep)
        try:
            self.halfmove_clock = int(halfmove)
            self.fullmove_number = max(1, int(fullmove))
        except ValueError:
            raise ValueError(f"invalid move counters: {fen!r}") from None

    def _clean_castling_rights(self) -> None:
        """Keep only castling rights whose king and rook are still on their squares."""
        rights = self.castling_rights & self.rooks
        if not (self.kings & self.occupied_co[WHITE] & BB_SQUARES[E1]):
            rights &= ~(BB_A1 | BB_H1)
        if not (self.kings & self.occupied_co[BLACK] & BB_SQUARES[E8]):
            rights &= ~(BB_A8 | BB_H8)
        rights &= ~((BB_A1 | BB_H1) & ~self.occupied_co[WHITE])
        rights &= ~((BB_A8 | BB_H8) & ~self.occupied_co[BLACK])
        self.castling_rights = rights & BB_CORNERS

    def _set_piece(self, sq: Square, piece_type: PieceType, color: Color) -> None:
        bb = BB_SQUARES[sq]
        self._remove_piece(sq)
        if piece_type == PAWN:
            self.pawns |= bb
        elif piece_type == KNIGHT:
            self.knights |= bb
        elif piece_type == BISHOP:
            self.bishops |= bb
        elif piece_type == ROOK:
            self.rooks |= bb
        elif piece_type == QUEEN:
            self.queens |= bb
        else:
            self.kings |= bb
        self.occupied_co[color] |= bb
        self.occupied |= bb

    def _remove_piece(self, sq: Square) -> PieceType | None:
        bb = BB_SQUARES[sq]
        if not self.occupied & bb:
            return None
        pt = self.piece_type_at(sq)
        mask = ~bb
        self.pawns &= mask
        self.knights &= mask
        self.bishops &= mask
        self.rooks &= mask
        self.queens &= mask
        self.kings &= mask
        self.occupied_co[0] &= mask
        self.occupied_co[1] &= mask
        self.occupied &= mask
        return pt

    def copy(self, stack: bool = True) -> Board:
        b = Board.__new__(Board)
        b.pawns, b.knights, b.bishops = self.pawns, self.knights, self.bishops
        b.rooks, b.queens, b.kings = self.rooks, self.queens, self.kings
        b.occupied_co = list(self.occupied_co)
        b.occupied = self.occupied
        b.turn = self.turn
        b.castling_rights = self.castling_rights
        b.ep_square = self.ep_square
        b.halfmove_clock = self.halfmove_clock
        b.fullmove_number = self.fullmove_number
        b.move_stack = list(self.move_stack) if stack else []
        b._stack = list(self._stack) if stack else []
        return b

    def __copy__(self) -> Board:
        return self.copy()

    # ------------------------------------------------------------- queries

    def piece_type_at(self, sq: Square) -> PieceType | None:
        bb = BB_SQUARES[sq]
        if not self.occupied & bb:
            return None
        if self.pawns & bb:
            return PAWN
        if self.knights & bb:
            return KNIGHT
        if self.bishops & bb:
            return BISHOP
        if self.rooks & bb:
            return ROOK
        if self.queens & bb:
            return QUEEN
        return KING

    def color_at(self, sq: Square) -> Color | None:
        bb = BB_SQUARES[sq]
        if self.occupied_co[WHITE] & bb:
            return WHITE
        if self.occupied_co[BLACK] & bb:
            return BLACK
        return None

    def piece_at(self, sq: Square) -> Piece | None:
        pt = self.piece_type_at(sq)
        if pt is None:
            return None
        return Piece(pt, bool(self.occupied_co[WHITE] & BB_SQUARES[sq]))

    def pieces_mask(self, piece_type: PieceType, color: Color) -> Bitboard:
        bb = (self.pawns, self.knights, self.bishops, self.rooks, self.queens,
              self.kings)[piece_type - 1]
        return bb & self.occupied_co[color]

    def king(self, color: Color) -> Square | None:
        bb = self.kings & self.occupied_co[color]
        return (bb & -bb).bit_length() - 1 if bb else None

    def ply(self) -> int:
        return 2 * (self.fullmove_number - 1) + (self.turn == BLACK)

    def attacks_mask(self, sq: Square) -> Bitboard:
        """Squares attacked by the piece on ``sq`` (0 if empty)."""
        bb = BB_SQUARES[sq]
        if bb & self.pawns:
            return PAWN_ATTACKS[bool(bb & self.occupied_co[WHITE])][sq]
        if bb & self.knights:
            return KNIGHT_ATTACKS[sq]
        if bb & self.kings:
            return KING_ATTACKS[sq]
        attacks = 0
        if bb & (self.bishops | self.queens):
            attacks = bishop_attacks(sq, self.occupied)
        if bb & (self.rooks | self.queens):
            attacks |= rook_attacks(sq, self.occupied)
        return attacks

    def _attackers(self, color: Color, sq: Square, occupied: Bitboard) -> Bitboard:
        queens_rooks = self.queens | self.rooks
        queens_bishops = self.queens | self.bishops
        return ((KNIGHT_ATTACKS[sq] & self.knights)
                | (KING_ATTACKS[sq] & self.kings)
                | (PAWN_ATTACKS[not color][sq] & self.pawns)
                | (rook_attacks(sq, occupied) & queens_rooks)
                | (bishop_attacks(sq, occupied) & queens_bishops)) \
            & self.occupied_co[color] & occupied

    def attackers_mask(self, color: Color, sq: Square) -> Bitboard:
        """Pieces of ``color`` attacking ``sq``."""
        return self._attackers(color, sq, self.occupied)

    def is_attacked_by(self, color: Color, sq: Square) -> bool:
        return bool(self._attackers(color, sq, self.occupied))

    def checkers_mask(self) -> Bitboard:
        king = self.king(self.turn)
        return 0 if king is None else self._attackers(not self.turn, king, self.occupied)

    def is_check(self) -> bool:
        return bool(self.checkers_mask())

    # ------------------------------------------------------------- move classification

    def is_en_passant(self, move: Move) -> bool:
        return (self.ep_square == move.to_square
                and bool(self.pawns & BB_SQUARES[move.from_square])
                and (move.to_square - move.from_square) in (7, 9, -7, -9)
                and not self.occupied & BB_SQUARES[move.to_square])

    def is_capture(self, move: Move) -> bool:
        return bool(BB_SQUARES[move.to_square] & self.occupied_co[not self.turn]) \
            or self.is_en_passant(move)

    def is_castling(self, move: Move) -> bool:
        return bool(self.kings & BB_SQUARES[move.from_square]) \
            and abs(square_file(move.from_square) - square_file(move.to_square)) == 2

    def is_kingside_castling(self, move: Move) -> bool:
        return self.is_castling(move) and move.to_square > move.from_square

    def is_queenside_castling(self, move: Move) -> bool:
        return self.is_castling(move) and move.to_square < move.from_square

    def is_zeroing(self, move: Move) -> bool:
        """Capture or pawn move: resets the 50-move counter."""
        return bool(self.pawns & BB_SQUARES[move.from_square]) or self.is_capture(move)

    def gives_check(self, move: Move) -> bool:
        self.push(move)
        try:
            return self.is_check()
        finally:
            self.pop()

    # ------------------------------------------------------------- making moves

    def push(self, move: Move) -> None:
        """Play ``move`` (assumed legal). Undo with :meth:`pop`."""
        self._stack.append((self.pawns, self.knights, self.bishops, self.rooks, self.queens,
                            self.kings, self.occupied_co[0], self.occupied_co[1],
                            self.turn, self.castling_rights, self.ep_square,
                            self.halfmove_clock, self.fullmove_number))
        self.move_stack.append(move)
        turn = self.turn
        ep = self.ep_square
        self.ep_square = None
        self.halfmove_clock += 1
        if turn == BLACK:
            self.fullmove_number += 1

        if not move:  # null move: just pass the turn
            self.turn = not turn
            return

        frm, to = move.from_square, move.to_square
        from_bb, to_bb = BB_SQUARES[frm], BB_SQUARES[to]
        piece = self.piece_type_at(frm)

        # castling rights disappear when a king or rook moves or a rook is captured
        self.castling_rights &= ~(from_bb | to_bb)
        if piece == KING:
            self.castling_rights &= ~(BB_RANK_1 if turn == WHITE else BB_RANK_8)

        if piece == PAWN:
            self.halfmove_clock = 0
            if to == ep and not self.occupied & to_bb:  # en passant: remove the pawn behind
                self._remove_piece(to - 8 if turn == WHITE else to + 8)
            elif abs(to - frm) == 16:
                self.ep_square = (frm + to) // 2
        if self.occupied & to_bb:
            self.halfmove_clock = 0

        self._remove_piece(frm)
        if piece == KING and abs(to - frm) == 2:  # castling: move the rook too
            if to > frm:
                self._set_piece(to - 1, ROOK, turn)
                self._remove_piece(to + 1)
            else:
                self._set_piece(to + 1, ROOK, turn)
                self._remove_piece(to - 2)
        self._set_piece(to, move.promotion or piece, turn)
        self.turn = not turn

    def pop(self) -> Move:
        """Undo the last move."""
        move = self.move_stack.pop()
        (self.pawns, self.knights, self.bishops, self.rooks, self.queens, self.kings,
         black, white, self.turn, self.castling_rights, self.ep_square,
         self.halfmove_clock, self.fullmove_number) = self._stack.pop()
        self.occupied_co = [black, white]
        self.occupied = black | white
        return move

    def peek(self) -> Move:
        return self.move_stack[-1]

    # ------------------------------------------------------------- move generation

    def generate_pseudo_legal_moves(self, from_mask: Bitboard = BB_ALL,
                                    to_mask: Bitboard = BB_ALL) -> Iterator[Move]:
        """Moves that follow the piece movement rules, ignoring king safety
        (and without castling, which is generated with its own checks)."""
        us = self.turn
        our = self.occupied_co[us]
        their = self.occupied_co[not us]
        occupied = self.occupied

        # pieces other than pawns
        for frm in scan_reversed(our & ~self.pawns & from_mask):
            targets = self.attacks_mask(frm) & ~our & to_mask
            for to in scan_reversed(targets):
                yield Move(frm, to)

        pawns = self.pawns & our & from_mask
        if not pawns:
            return
        promo_rank = BB_RANK_8 if us == WHITE else BB_RANK_1
        attacks = PAWN_ATTACKS[us]

        # captures
        for frm in scan_reversed(pawns):
            for to in scan_reversed(attacks[frm] & their & to_mask):
                if BB_SQUARES[to] & promo_rank:
                    for p in _PROMOTIONS:
                        yield Move(frm, to, p)
                else:
                    yield Move(frm, to)

        # pushes
        if us == WHITE:
            single = (pawns << 8) & ~occupied
            double = ((single & BB_RANK_3) << 8) & ~occupied
            back = -8
        else:
            single = (pawns >> 8) & ~occupied
            double = ((single & BB_RANK_6) >> 8) & ~occupied
            back = 8
        for to in scan_reversed(single & to_mask):
            frm = to + back
            if BB_SQUARES[to] & promo_rank:
                for p in _PROMOTIONS:
                    yield Move(frm, to, p)
            else:
                yield Move(frm, to)
        for to in scan_reversed(double & to_mask):
            yield Move(to + 2 * back, to)

        # en passant
        ep = self.ep_square
        if ep is not None and BB_SQUARES[ep] & to_mask and not occupied & BB_SQUARES[ep]:
            for frm in scan_reversed(pawns & PAWN_ATTACKS[not us][ep]):
                yield Move(frm, ep)

    def _slider_blockers(self, king: Square) -> Bitboard:
        """Our pieces pinned to our king (the only piece between it and an enemy slider)."""
        them = self.occupied_co[not self.turn]
        snipers = ((rook_attacks(king, 0) & (self.rooks | self.queens))
                   | (bishop_attacks(king, 0) & (self.bishops | self.queens))) & them
        blockers = 0
        for sniper in scan_reversed(snipers):
            b = BETWEEN[king][sniper] & self.occupied
            if b and not b & (b - 1):  # exactly one piece in between
                blockers |= b
        return blockers & self.occupied_co[self.turn]

    def _ep_is_safe(self, king: Square, move: Move) -> bool:
        """En passant removes two pawns from a line at once, so check it directly."""
        captured = move.to_square - 8 if self.turn == WHITE else move.to_square + 8
        occupied = ((self.occupied & ~BB_SQUARES[move.from_square] & ~BB_SQUARES[captured])
                    | BB_SQUARES[move.to_square])
        them = self.occupied_co[not self.turn] & ~BB_SQUARES[captured]
        attackers = ((rook_attacks(king, occupied) & (self.rooks | self.queens))
                     | (bishop_attacks(king, occupied) & (self.bishops | self.queens))
                     | (KNIGHT_ATTACKS[king] & self.knights)
                     | (PAWN_ATTACKS[self.turn][king] & self.pawns)) & them
        return not attackers

    def _king_move_is_safe(self, king: Square, to: Square) -> bool:
        # the king itself must not block a slider's view of the square it moves to
        occupied = self.occupied & ~BB_SQUARES[king]
        return not self._attackers(not self.turn, to, occupied | BB_SQUARES[to]) & \
            ~BB_SQUARES[to]

    def _castling_moves(self, king: Square, from_mask: Bitboard,
                        to_mask: Bitboard) -> Iterator[Move]:
        us = self.turn
        if not (BB_SQUARES[king] & from_mask):
            return
        rights = self.castling_rights & (BB_RANK_1 if us == WHITE else BB_RANK_8)
        them = not us
        home = E1 if us == WHITE else E8
        if king != home:
            return
        # kingside: f and g empty, and neither attacked
        if rights & BB_SQUARES[home + 3] and BB_SQUARES[home + 2] & to_mask:
            if not self.occupied & (BB_SQUARES[home + 1] | BB_SQUARES[home + 2]) and \
                    not self.is_attacked_by(them, home + 1) and \
                    not self.is_attacked_by(them, home + 2):
                yield Move(home, home + 2)
        # queenside: b, c, d empty; c and d not attacked
        if rights & BB_SQUARES[home - 4] and BB_SQUARES[home - 2] & to_mask:
            empty = BB_SQUARES[home - 1] | BB_SQUARES[home - 2] | BB_SQUARES[home - 3]
            if not self.occupied & empty and \
                    not self.is_attacked_by(them, home - 1) and \
                    not self.is_attacked_by(them, home - 2):
                yield Move(home, home - 2)

    def generate_legal_moves(self, from_mask: Bitboard = BB_ALL,
                             to_mask: Bitboard = BB_ALL) -> Iterator[Move]:
        king = self.king(self.turn)
        if king is None:  # not a real position, but don't crash
            yield from self.generate_pseudo_legal_moves(from_mask, to_mask)
            return
        checkers = self._attackers(not self.turn, king, self.occupied)
        blockers = self._slider_blockers(king)
        king_bb = BB_SQUARES[king]
        ep = self.ep_square

        if checkers:
            # 1. king steps to a safe square
            if king_bb & from_mask:
                targets = KING_ATTACKS[king] & ~self.occupied_co[self.turn] & to_mask
                for to in scan_reversed(targets):
                    if self._king_move_is_safe(king, to):
                        yield Move(king, to)
            if checkers & (checkers - 1):
                return  # double check: only the king can move
            # 2. capture the checker or block the line
            checker = (checkers & -checkers).bit_length() - 1
            target = (BETWEEN[king][checker] | checkers) & to_mask
            for move in self.generate_pseudo_legal_moves(from_mask & ~king_bb, target):
                if self.is_en_passant(move):
                    continue  # handled below
                if not blockers & BB_SQUARES[move.from_square] or \
                        RAYS[king][move.from_square] & BB_SQUARES[move.to_square]:
                    yield move
            # 3. en passant capturing the pawn that just gave check
            if ep is not None and BB_SQUARES[ep] & to_mask:
                captured = ep - 8 if self.turn == WHITE else ep + 8
                if checkers & BB_SQUARES[captured]:
                    for move in self.generate_pseudo_legal_moves(from_mask & self.pawns,
                                                                 BB_SQUARES[ep]):
                        if self.is_en_passant(move) and self._ep_is_safe(king, move):
                            yield move
            return

        for move in self.generate_pseudo_legal_moves(from_mask, to_mask):
            frm = move.from_square
            if frm == king:
                if self._king_move_is_safe(king, move.to_square):
                    yield move
            elif move.to_square == ep and self.is_en_passant(move):
                if self._ep_is_safe(king, move):
                    yield move
            elif not blockers & BB_SQUARES[frm] or RAYS[king][frm] & BB_SQUARES[move.to_square]:
                yield move
        yield from self._castling_moves(king, from_mask, to_mask)

    def generate_legal_captures(self) -> Iterator[Move]:
        """Legal captures, including en passant (and capturing promotions)."""
        yield from self.generate_legal_moves(BB_ALL, self.occupied_co[not self.turn])
        ep = self.ep_square
        if ep is not None:
            # only pawns capture en passant; other pieces may also reach the empty
            # en passant square, but that is not a capture
            for move in self.generate_legal_moves(self.pawns, BB_SQUARES[ep]):
                if self.is_en_passant(move):
                    yield move

    @property
    def legal_moves(self) -> LegalMoves:
        return LegalMoves(self)

    def is_legal(self, move) -> bool:
        if not isinstance(move, Move) or not move:
            return False
        return any(m == move for m in self.generate_legal_moves(
            BB_SQUARES[move.from_square], BB_SQUARES[move.to_square]))

    def has_legal_en_passant(self) -> bool:
        ep = self.ep_square
        if ep is None:
            return False
        pawns = self.pawns & self.occupied_co[self.turn] & PAWN_ATTACKS[not self.turn][ep]
        return bool(pawns) and any(self.is_en_passant(m) for m in self.generate_legal_moves(
            pawns, BB_SQUARES[ep]))

    # ------------------------------------------------------------- game end

    def is_checkmate(self) -> bool:
        return self.is_check() and not any(True for _ in self.generate_legal_moves())

    def is_stalemate(self) -> bool:
        return not self.is_check() and not any(True for _ in self.generate_legal_moves())

    def has_insufficient_material(self, color: Color) -> bool:
        """True if ``color`` cannot possibly checkmate (K, K+N, K+B on one colour...)."""
        ours = self.occupied_co[color]
        if ours & (self.pawns | self.rooks | self.queens):
            return False
        if ours & self.knights:
            # a lone knight can only mate if the opponent has pieces to block with
            return popcount(ours) <= 2 and \
                not self.occupied_co[not color] & ~self.kings & ~self.queens
        if ours & self.bishops:
            same_colour = not self.bishops & BB_DARK_SQUARES or \
                not self.bishops & BB_LIGHT_SQUARES
            return same_colour and not self.pawns and not self.knights
        return True

    def is_insufficient_material(self) -> bool:
        return self.has_insufficient_material(WHITE) and self.has_insufficient_material(BLACK)

    def position_key(self) -> tuple:
        """Identity of the position for repetitions and the transposition table:
        pieces, side to move, castling rights and (only if it can really be played)
        the en passant square."""
        return (self.pawns, self.knights, self.bishops, self.rooks, self.queens, self.kings,
                self.occupied_co[WHITE], self.occupied_co[BLACK], self.turn,
                self.castling_rights,
                self.ep_square if self.ep_square is not None and self.has_legal_en_passant()
                else None)

    def is_repetition(self, count: int = 3) -> bool:
        """Has the current position occurred ``count`` times (including now)?"""
        key = self.position_key()
        seen = 1
        b = self.copy()
        for _ in range(min(self.halfmove_clock, len(self.move_stack))):
            b.pop()
            if b.position_key() == key:
                seen += 1
                if seen >= count:
                    return True
        return False

    def outcome(self, claim_draw: bool = False) -> Outcome | None:
        """How the game ended, or None. Without ``claim_draw`` only automatic endings
        count; with it, threefold repetition and the 50-move rule count too."""
        if self.is_checkmate():
            return Outcome(Termination.CHECKMATE, not self.turn)
        if self.is_insufficient_material():
            return Outcome(Termination.INSUFFICIENT_MATERIAL, None)
        if not any(True for _ in self.generate_legal_moves()):
            return Outcome(Termination.STALEMATE, None)
        if self.halfmove_clock >= 150:
            return Outcome(Termination.SEVENTYFIVE_MOVES, None)
        if self.is_repetition(5):
            return Outcome(Termination.FIVEFOLD_REPETITION, None)
        if claim_draw:
            if self.halfmove_clock >= 100:
                return Outcome(Termination.FIFTY_MOVES, None)
            if self.is_repetition(3):
                return Outcome(Termination.THREEFOLD_REPETITION, None)
        return None

    def is_game_over(self, claim_draw: bool = False) -> bool:
        return self.outcome(claim_draw) is not None

    def is_valid(self) -> bool:
        return not self.status()

    def status(self) -> list[str]:
        """Problems that make the position impossible (empty list = valid)."""
        problems = []
        for color in COLORS:
            n = popcount(self.kings & self.occupied_co[color])
            if n != 1:
                problems.append(f"{COLOR_NAMES[color]} has {n} kings")
            if popcount(self.occupied_co[color]) > 16:
                problems.append(f"{COLOR_NAMES[color]} has more than 16 pieces")
            if popcount(self.pawns & self.occupied_co[color]) > 8:
                problems.append(f"{COLOR_NAMES[color]} has more than 8 pawns")
        if self.pawns & (BB_RANK_1 | BB_RANK_8):
            problems.append("pawns on the first or last rank")
        if not problems:
            other_king = self.king(not self.turn)
            if self._attackers(self.turn, other_king, self.occupied):
                problems.append("the side not to move is in check")
        return problems

    # ------------------------------------------------------------- FEN

    def board_fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row, empty = "", 0
            for file in range(8):
                piece = self.piece_at(square(file, rank))
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += piece.symbol()
            if empty:
                row += str(empty)
            rows.append(row)
        return "/".join(rows)

    def castling_fen(self) -> str:
        out = "".join(ch for ch, bb in (("K", BB_H1), ("Q", BB_A1), ("k", BB_H8), ("q", BB_A8))
                      if self.castling_rights & bb)
        return out or "-"

    def fen(self) -> str:
        ep = SQUARE_NAMES[self.ep_square] if self.has_legal_en_passant() else "-"
        return (f"{self.board_fen()} {'w' if self.turn else 'b'} {self.castling_fen()} {ep} "
                f"{self.halfmove_clock} {self.fullmove_number}")

    def __repr__(self) -> str:
        return f"Board({self.fen()!r})"

    def __str__(self) -> str:
        return self.unicode(ascii_only=True)

    def unicode(self, invert_color: bool = False, borders: bool = False,
                orientation: Color = WHITE, ascii_only: bool = False) -> str:
        """Text picture of the board (for terminals)."""
        lines = []
        ranks = range(7, -1, -1) if orientation == WHITE else range(8)
        files = range(8) if orientation == WHITE else range(7, -1, -1)
        for rank in ranks:
            cells = []
            for file in files:
                piece = self.piece_at(square(file, rank))
                if piece is None:
                    cells.append("." if (ascii_only or not borders) else " ")
                    continue
                symbol = piece.symbol()
                if not ascii_only:
                    if invert_color:
                        symbol = symbol.swapcase()
                    symbol = UNICODE_PIECES[symbol]
                cells.append(symbol)
            if borders:
                lines.append(f"{RANK_NAMES[rank]} |" + "|".join(cells) + "|")
            else:
                lines.append(" ".join(cells))
        if borders:
            lines.append("   " + " ".join(FILE_NAMES[f] for f in files))
        return "\n".join(lines)

    def mirror(self) -> Board:
        """The same position with colours swapped and the board flipped."""
        b = Board(None)
        b.pawns, b.knights = flip_vertical(self.pawns), flip_vertical(self.knights)
        b.bishops, b.rooks = flip_vertical(self.bishops), flip_vertical(self.rooks)
        b.queens, b.kings = flip_vertical(self.queens), flip_vertical(self.kings)
        b.occupied_co = [flip_vertical(self.occupied_co[WHITE]),
                         flip_vertical(self.occupied_co[BLACK])]
        b.occupied = b.occupied_co[0] | b.occupied_co[1]
        b.turn = not self.turn
        b.castling_rights = flip_vertical(self.castling_rights)
        b.ep_square = None if self.ep_square is None else self.ep_square ^ 56
        b.halfmove_clock = self.halfmove_clock
        b.fullmove_number = self.fullmove_number
        return b

    # ------------------------------------------------------------- SAN / UCI

    def _san_core(self, move: Move) -> str:
        """SAN without the check/mate suffix."""
        if self.is_castling(move):
            return "O-O" if move.to_square > move.from_square else "O-O-O"
        piece = self.piece_type_at(move.from_square)
        capture = self.is_capture(move)
        to_name = SQUARE_NAMES[move.to_square]
        if piece == PAWN:
            san = (FILE_NAMES[square_file(move.from_square)] + "x" if capture else "") + to_name
            if move.promotion:
                san += "=" + PIECE_SYMBOLS[move.promotion].upper()
            return san
        san = PIECE_SYMBOLS[piece].upper()
        # disambiguation: other pieces of the same type that can reach the same square
        others = self.pieces_mask(piece, self.turn) & ~BB_SQUARES[move.from_square]
        rivals = [m.from_square for m in self.generate_legal_moves(
            others, BB_SQUARES[move.to_square])] if others else []
        if rivals:
            f, r = square_file(move.from_square), square_rank(move.from_square)
            if all(square_file(s) != f for s in rivals):
                san += FILE_NAMES[f]
            elif all(square_rank(s) != r for s in rivals):
                san += RANK_NAMES[r]
            else:
                san += SQUARE_NAMES[move.from_square]
        return san + ("x" if capture else "") + to_name

    def san(self, move: Move) -> str:
        """Standard Algebraic Notation, e.g. 'Nf3', 'exd5', 'O-O', 'e8=Q+', 'Qh5#'."""
        if not move:
            return "--"
        san = self._san_core(move)
        self.push(move)
        try:
            if self.is_check():
                san += "#" if not any(True for _ in self.generate_legal_moves()) else "+"
        finally:
            self.pop()
        return san

    def parse_san(self, san: str) -> Move:
        text = san.strip().rstrip("+#!?").replace("0", "O")
        if text in ("--", "Z0", "OOOO"):
            return Move.null()
        if text.lower() in ("o-o", "o-o-o"):
            text = text.upper()
        normal = text.replace("=", "")
        for move in self.generate_legal_moves():
            core = self._san_core(move)
            if core == text or core.replace("=", "") == normal:
                return move
            # tolerate a missing 'x' (e.g. "Nf3d4" style is not supported, "ed5" is)
            if core.replace("x", "") == normal.replace("x", "") and \
                    self.piece_type_at(move.from_square) != PAWN:
                return move
        raise ValueError(f"illegal or ambiguous san: {san!r} in {self.fen()}")

    def push_san(self, san: str) -> Move:
        move = self.parse_san(san)
        self.push(move)
        return move

    def parse_uci(self, uci: str) -> Move:
        move = Move.from_uci(uci)
        if not self.is_legal(move):
            raise ValueError(f"illegal uci: {uci!r} in {self.fen()}")
        return move

    def push_uci(self, uci: str) -> Move:
        move = self.parse_uci(uci)
        self.push(move)
        return move

    def variation_san(self, moves: Iterable[Move]) -> str:
        """A line of moves as text: '1. e4 e5 2. Nf3' (or '5... Nxd5 6. Nc3')."""
        b = self.copy(stack=False)
        out = []
        for i, move in enumerate(moves):
            if b.turn == WHITE:
                out.append(f"{b.fullmove_number}. {b.san(move)}")
            elif i == 0:
                out.append(f"{b.fullmove_number}... {b.san(move)}")
            else:
                out.append(b.san(move))
            b.push(move)
        return " ".join(out)
