"""Reading and writing games in PGN (Portable Game Notation), written from scratch.

PGN is the text format every chess site and program uses::

    [Event "Human vs AI"]
    [White "You"]
    [Black "Chess Minimax AI"]
    [Result "1-0"]

    1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0

Only the main line is read; comments ``{...}``, ``; ...``, variations ``(...)`` and
annotation symbols ``$1`` are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from chess_ai.chess.core import STARTING_FEN, WHITE, Board, Move

RESULTS = ("1-0", "0-1", "1/2-1/2", "*")
SEVEN_TAG_ROSTER = ("Event", "Site", "Date", "Round", "White", "Black", "Result")

_HEADER = re.compile(r'^\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]\s*$')
_MOVE_NUMBER = re.compile(r"^\d+\.+")


@dataclass
class PgnGame:
    headers: dict[str, str] = field(default_factory=dict)
    start_fen: str = STARTING_FEN
    moves: list[Move] = field(default_factory=list)

    def board(self) -> Board:
        """The starting position (before any move)."""
        return Board(self.start_fen)

    def end_board(self) -> Board:
        b = self.board()
        for m in self.moves:
            b.push(m)
        return b


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_pgn(headers: dict[str, str], moves: list[Move], start_fen: str = STARTING_FEN,
              result: str = "*") -> str:
    """PGN text for a game. ``headers`` may contain any tags; the Seven Tag Roster
    comes first, and FEN/SetUp tags are added for non-standard starting positions."""
    tags = dict(headers)
    tags["Result"] = result
    if start_fen != STARTING_FEN:
        tags["SetUp"] = "1"
        tags["FEN"] = start_fen
    lines = [f'[{k} "{_escape(tags.get(k, "?"))}"]' for k in SEVEN_TAG_ROSTER]
    lines += [f'[{k} "{_escape(v)}"]' for k, v in tags.items() if k not in SEVEN_TAG_ROSTER]

    board = Board(start_fen)
    tokens = []
    for i, move in enumerate(moves):
        if board.turn == WHITE:
            tokens.append(f"{board.fullmove_number}.")
        elif i == 0:
            tokens.append(f"{board.fullmove_number}...")
        tokens.append(board.san(move))
        board.push(move)
    tokens.append(result)

    text, line = [], ""
    for tok in tokens:  # wrap movetext at 80 characters
        if line and len(line) + 1 + len(tok) > 80:
            text.append(line)
            line = tok
        else:
            line = f"{line} {tok}" if line else tok
    text.append(line)
    return "\n".join(lines) + "\n\n" + "\n".join(text) + "\n"


def _strip_movetext(text: str) -> str:
    """Remove comments, variations and annotation glyphs from movetext."""
    out, depth, i = [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            end = text.find("}", i)
            i = len(text) if end < 0 else end + 1
            continue
        if ch == ";":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
        i += 1
    return "".join(out)


def read_pgn(text: str) -> PgnGame:
    """Parse the first game in ``text``. Raises ValueError for empty or broken PGN."""
    headers: dict[str, str] = {}
    body_lines = []
    in_body = False
    for raw in text.splitlines():
        line = raw.strip()
        if not in_body and line.startswith("["):
            m = _HEADER.match(line)
            if not m:
                raise ValueError(f"bad PGN header: {line!r}")
            headers[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
            continue
        if line:
            in_body = True
        if in_body and line.startswith("[") and body_lines:
            break  # the next game starts
        body_lines.append(raw)

    movetext = _strip_movetext("\n".join(body_lines))
    tokens = [t for t in movetext.split() if not t.startswith("$")]
    if not headers and not tokens:
        raise ValueError("no game found in PGN text")

    start_fen = headers.get("FEN", STARTING_FEN)
    try:
        board = Board(start_fen)
    except ValueError as exc:
        raise ValueError(f"bad FEN in PGN: {exc}") from exc
    moves = []
    for tok in tokens:
        if tok in RESULTS:
            break
        tok = _MOVE_NUMBER.sub("", tok)
        if not tok:
            continue
        try:
            move = board.parse_san(tok)
        except ValueError as exc:
            raise ValueError(f"illegal move {tok!r} in PGN (after {len(moves)} moves)") from exc
        board.push(move)
        moves.append(move)
    return PgnGame(headers=headers, start_fen=start_fen, moves=moves)
