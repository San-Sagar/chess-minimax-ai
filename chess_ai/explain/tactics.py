"""Detect what a move *does* on the board: captures, checks, forks, pins, threats...

Everything here is computed by comparing the position before and after the move with
our own rules engine, so each sentence the AI Thinking panel shows is a checked fact,
not a guess. Facts carry a weight so the most important ones are told first.
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_ai import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9,
         chess.KING: 100}
NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
        chess.QUEEN: "queen", chess.KING: "king"}
CENTRE = {chess.parse_square(s) for s in ("d4", "e4", "d5", "e5")}
ORDINAL = {3: "3rd", 4: "4th", 5: "5th", 6: "6th", 7: "7th"}


@dataclass(frozen=True)
class Fact:
    kind: str  # e.g. "capture", "fork", "pin", "check"
    text: str  # sentence fragment: "captures the pawn on e5"
    weight: int  # higher = more important

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "weight": self.weight}


def piece_on(board: chess.Board, sq: int) -> str:
    """'the knight on c6'"""
    pt = board.piece_type_at(sq)
    return f"the {NAME[pt]} on {chess.square_name(sq)}" if pt else chess.square_name(sq)


def _attackers(board: chess.Board, color: bool, sq: int) -> list[int]:
    return list(chess.scan_forward(board.attackers_mask(color, sq)))


def is_hanging(board: chess.Board, sq: int) -> bool:
    """A piece that can be won: attacked and either undefended or attacked by a
    cheaper piece. (Kings are never 'hanging'; that is check.)"""
    pt = board.piece_type_at(sq)
    color = board.color_at(sq)
    if pt is None or pt == chess.KING:
        return False
    attackers = _attackers(board, not color, sq)
    if not attackers:
        return False
    if not _attackers(board, color, sq):
        return True
    cheapest = min(VALUE[board.piece_type_at(a)] for a in attackers)
    return cheapest < VALUE[pt]


def _hanging_pieces(board: chess.Board, color: bool) -> set[int]:
    return {sq for sq in chess.scan_forward(board.occupied_co[color]) if is_hanging(board, sq)}


def _pins(board: chess.Board, by: bool) -> set[tuple[int, int, int]]:
    """(pinner, pinned, target) where an enemy piece is pinned to its king or queen."""
    out = set()
    them = not by
    targets = board.pieces_mask(chess.KING, them) | board.pieces_mask(chess.QUEEN, them)
    for target in chess.scan_forward(targets):
        for pinner in chess.scan_forward(board.occupied_co[by] & (board.rooks | board.bishops
                                                                   | board.queens)):
            line = chess.RAYS[target][pinner]
            if not line:
                continue
            pt = board.piece_type_at(pinner)
            straight = chess.square_rank(target) == chess.square_rank(pinner) or \
                chess.square_file(target) == chess.square_file(pinner)
            if (pt == chess.ROOK and not straight) or (pt == chess.BISHOP and straight):
                continue
            between = chess.BETWEEN[target][pinner] & board.occupied
            if between and not between & (between - 1) and between & board.occupied_co[them]:
                pinned = chess.lsb(between)
                if VALUE[board.piece_type_at(pinned)] < VALUE[board.piece_type_at(target)]:
                    out.add((pinner, pinned, target))
    return out


def _new_attacks(before: chess.Board, after: chess.Board, sq_before: int | None,
                 sq_after: int, color: bool) -> set[int]:
    """Enemy pieces attacked from ``sq_after`` now that were not attacked from
    ``sq_before`` (the same piece's previous square) before."""
    them = after.occupied_co[not color]
    now = after.attacks_mask(sq_after) & them
    old = before.attacks_mask(sq_before) if sq_before is not None else 0
    return set(chess.scan_forward(now & ~old))


def move_facts(board: chess.Board, move: chess.Move, line: list[chess.Move] | None = None
               ) -> list[Fact]:
    """Facts about ``move`` played in ``board`` (the board is not changed).

    ``line``: the expected continuation starting with ``move`` (used to check that a
    piece left 'en prise' is really safe to leave there).
    """
    facts: list[Fact] = []
    us = board.turn
    them = not us
    frm, to = move.from_square, move.to_square
    piece = board.piece_type_at(frm)
    pname = NAME[piece]
    after = board.copy()
    after.push(move)

    # ---------------------------------------------------------------- forcing moves
    if after.is_checkmate():
        return [Fact("checkmate", "delivers checkmate", 100)]
    if board.is_castling(move):
        side = "kingside" if move.to_square > move.from_square else "queenside"
        facts.append(Fact("castle", f"castles {side}, tucking the king away and bringing "
                                    "the rook into play", 30))
    if board.is_capture(move):
        victim = chess.PAWN if board.is_en_passant(move) else board.piece_type_at(to)
        how = " en passant" if board.is_en_passant(move) else ""
        recapture = bool(board.move_stack) and board.peek().to_square == to
        verb = "recaptures" if recapture else "captures"
        facts.append(Fact("capture", f"{verb} the {NAME[victim]} on {chess.square_name(to)}{how}",
                          40 + 5 * VALUE[victim]))
    if move.promotion:
        facts.append(Fact("promotion", f"promotes the pawn to a {NAME[move.promotion]}", 90))
    if after.is_check():
        checkers = list(chess.scan_forward(after.checkers_mask()))
        if any(c != to for c in checkers):
            facts.append(Fact("check", "gives a discovered check", 55))
        else:
            facts.append(Fact("check", "gives check", 50))

    # ---------------------------------------------------------------- safety of our pieces
    hanging_before = _hanging_pieces(board, us)
    hanging_after = _hanging_pieces(after, us)
    if frm in hanging_before and to not in hanging_after:
        facts.append(Fact("escape", f"moves the {pname} out of danger (it was attacked on "
                                    f"{chess.square_name(frm)})", 45))
    saved = (hanging_before - {frm}) - hanging_after
    saved = {sq for sq in saved if after.piece_type_at(sq) is not None}
    if saved:
        sq = max(saved, key=lambda s: VALUE[after.piece_type_at(s)])
        facts.append(Fact("defend", f"protects {piece_on(after, sq)}, which was under attack",
                          38 + VALUE[after.piece_type_at(sq)]))
    if to in hanging_after and piece != chess.KING:
        reply = line[1] if line and len(line) > 1 else None
        if reply is None or reply.to_square != to:
            facts.append(Fact("sacrifice", f"leaves the {pname} where it can be taken, because "
                                           "the search found that taking it does not pay", 35))

    # ---------------------------------------------------------------- attacks we create
    new = _new_attacks(board, after, frm, to, us)
    if after.is_check():
        new.discard(after.king(them))
    valuable = [sq for sq in new
                if VALUE[after.piece_type_at(sq)] > VALUE[piece] or is_hanging(after, sq)]
    king_attacked = after.is_check() and any(c == to for c in chess.scan_forward(after.checkers_mask()))
    fork_targets = valuable + ([after.king(them)] if king_attacked else [])
    if len(fork_targets) >= 2:
        names = " and ".join(piece_on(after, sq) for sq in
                             sorted(fork_targets, key=lambda s: -VALUE[after.piece_type_at(s)])[:2])
        facts.append(Fact("fork", f"forks {names}", 75))
    elif valuable:
        sq = max(valuable, key=lambda s: VALUE[after.piece_type_at(s)])
        extra = ", which is undefended" if not _attackers(after, them, sq) else ""
        facts.append(Fact("attack", f"attacks {piece_on(after, sq)}{extra}",
                          32 + VALUE[after.piece_type_at(sq)]))

    # discovered attacks: other pieces of ours that now see a target
    for sq in chess.scan_forward(after.occupied_co[us] & ~chess.BB_SQUARES[to]
                                 & (after.bishops | after.rooks | after.queens)):
        gained = (after.attacks_mask(sq) & ~board.attacks_mask(sq)) & after.occupied_co[them]
        gained &= ~after.kings
        for target in chess.scan_forward(gained):
            if VALUE[after.piece_type_at(target)] >= 3 and is_hanging(after, target):
                facts.append(Fact("discovered", f"opens the line for {piece_on(after, sq)} "
                                                f"to attack {piece_on(after, target)}", 40))
                break

    # pins
    new_pins = _pins(after, us) - _pins(board, us)
    for _pinner, pinned, target in sorted(new_pins)[:1]:
        facts.append(Fact("pin", f"pins {piece_on(after, pinned)} to "
                                 f"the {NAME[after.piece_type_at(target)]}", 45))

    # ---------------------------------------------------------------- positional ideas
    rank_rel = chess.square_rank(to) if us == chess.WHITE else 7 - chess.square_rank(to)
    from_rank_rel = chess.square_rank(frm) if us == chess.WHITE else 7 - chess.square_rank(frm)
    if piece in (chess.KNIGHT, chess.BISHOP) and from_rank_rel == 0 and board.fullmove_number <= 15:
        facts.append(Fact("develop", f"develops the {pname}", 20))
    if piece == chess.PAWN and to in CENTRE and not board.is_capture(move):
        facts.append(Fact("centre", "takes space in the centre", 18))
    elif piece in (chess.KNIGHT, chess.BISHOP) and to in CENTRE:
        facts.append(Fact("centre", f"puts the {pname} on a strong central square", 16))
    if piece == chess.PAWN and rank_rel >= 4:
        blockers = 0
        f = chess.square_file(to)
        for df in (-1, 0, 1):
            if 0 <= f + df < 8:
                blockers |= chess.BB_FILES[f + df]
        ahead = 0
        for r in (range(chess.square_rank(to) + 1, 8) if us == chess.WHITE
                  else range(0, chess.square_rank(to))):
            ahead |= chess.BB_RANKS[r]
        if not (after.pawns & after.occupied_co[them] & blockers & ahead) and not move.promotion:
            facts.append(Fact("passed", f"pushes the passed pawn to the {ORDINAL.get(rank_rel + 1, f'{rank_rel + 1}th')} rank",
                              30 + 5 * rank_rel))
    if piece == chess.ROOK and not (after.pawns & chess.BB_FILES[chess.square_file(to)]) and \
            (board.pawns & chess.BB_FILES[chess.square_file(frm)] or
             chess.square_file(frm) != chess.square_file(to)):
        facts.append(Fact("open_file", f"puts the rook on the open {chess.FILE_NAMES[chess.square_file(to)]}-file", 22))
    if piece == chess.KING and not board.is_castling(move) and \
            not (board.queens) and _centre_distance(to) < _centre_distance(frm):
        facts.append(Fact("king_activity", "brings the king towards the centre, where it is "
                                           "strong in the endgame", 18))

    facts.sort(key=lambda f: f.weight, reverse=True)
    return facts


def _centre_distance(sq: int) -> float:
    f, r = chess.square_file(sq), chess.square_rank(sq)
    return abs(f - 3.5) + abs(r - 3.5)


def describe_move(board: chess.Board, move: chess.Move) -> str:
    """'Knight g1 → f3'"""
    pt = board.piece_type_at(move.from_square)
    return (f"{NAME[pt].capitalize()} {chess.square_name(move.from_square)} → "
            f"{chess.square_name(move.to_square)}")


def threats_against(board: chess.Board, color: bool) -> list[int]:
    """Squares of ``color``'s pieces that the opponent could win right now."""
    return sorted(_hanging_pieces(board, color),
                  key=lambda s: -VALUE[board.piece_type_at(s)])
