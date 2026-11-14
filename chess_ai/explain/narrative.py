"""Turn an AI move report into a plain-language explanation (the AI Thinking panel).

Input: the position before the move and the report the engine produced (search
statistics, candidate moves with exact scores, what alpha-beta did with every root
move, how the choice changed with depth). Output: a dict of short sections:

* ``headline`` / ``assessment``: the move and how the AI judges the position
* ``ideas``: what the move does, from :mod:`tactics` (checked on the board)
* ``expected``: the line it expects and the opponent's likely reply
* ``alternatives``: the runner-up moves, how much worse, and the refuting reply
* ``refuted``: tempting captures/checks that alpha-beta proved bad, and how quickly
* ``eval_changes``: which evaluation terms the line improves or worsens
* ``search`` / ``depth_story``: how minimax with alpha-beta found the move

Every sentence comes from the data; nothing is made up.
"""

from __future__ import annotations

from chess_ai import chess
from chess_ai.engine.classic import MATE_SCORE
from chess_ai.engine.evaluation import TERM_LABELS
from chess_ai.engine.search import MATE_THRESHOLD, format_score
from chess_ai.explain.tactics import describe_move, move_facts


def _side(color_white: bool) -> str:
    return "White" if color_white else "Black"


def assessment(score: int | None, ai_white: bool) -> str:
    """'The AI thinks it is clearly better (+1.40).'"""
    if score is None:
        return "No search was needed, so there is no score for this move."
    text = format_score(score)
    if abs(score) >= MATE_THRESHOLD:
        n = (MATE_SCORE - abs(score) + 1) // 2  # plies to mate -> moves
        return (f"The AI sees a forced checkmate in {n} ({text})." if score > 0 else
                f"The AI sees that it is getting checkmated in {n} ({text}) and resists "
                "as long as possible.")
    a = abs(score)
    if a < 30:
        verdict = "the position is about equal"
    elif a < 100:
        verdict = "it is slightly better" if score > 0 else "it is slightly worse"
    elif a < 300:
        verdict = "it is clearly better" if score > 0 else "it is clearly worse"
    else:
        verdict = "it is winning" if score > 0 else "it is losing"
    return f"The AI thinks {verdict} ({text} from {_side(ai_white)}'s point of view)."


def _sentence(fragment: str) -> str:
    return fragment[0].upper() + fragment[1:] + "."


def _numbered_line(board: chess.Board, ucis: list[str]) -> str:
    moves = []
    b = board.copy()
    for u in ucis:
        m = chess.Move.from_uci(u)
        if m not in b.legal_moves:
            break
        moves.append(m)
        b.push(m)
    return board.variation_san(moves)


def _reply_idea(board_after_move: chess.Board, reply_uci: str | None) -> str | None:
    if not reply_uci:
        return None
    reply = chess.Move.from_uci(reply_uci)
    if reply not in board_after_move.legal_moves:
        return None
    facts = move_facts(board_after_move, reply)
    return facts[0].text if facts else None


def _book_explanation(board: chess.Board, report: dict) -> dict:
    move = chess.Move.from_uci(report["move"])
    opening = report.get("opening")
    book = report.get("book") or {}
    options = book.get("options", [])
    ideas = [_sentence(f.text) for f in move_facts(board, move)[:3]]
    name = f" ({opening['name']}, ECO {opening['eco']})" if opening else ""
    known = ", ".join(f"{o['san']} {round(o['share'] * 100)}%" for o in options[:5])
    return {
        "kind": "book",
        "headline": f"{report['san']}: {describe_move(board, move)}",
        "assessment": f"An opening book move{name}. Opening theory is centuries of human "
                      "experience, so the AI plays it instantly instead of searching.",
        "ideas": ideas,
        "book": {"known_moves": known, "choice": "picked at random, weighted by how often "
                                                 "each move appears in the book"},
        "expected": None, "alternatives": [], "refuted": [], "eval_changes": [],
        "search": [], "depth_story": [], "difficulty_note": None,
    }


def explain_report(board: chess.Board, report: dict) -> dict:
    """Explanation for an AI move. ``board`` is the position *before* the move."""
    if report.get("source") == "book" or not report.get("analysis"):
        return _book_explanation(board, report)

    a = report["analysis"]
    ai_white = board.turn == chess.WHITE
    move = chess.Move.from_uci(report["move"])
    best = a["best"]
    played = next((c for c in a["candidates"] if c["move"] == report["move"]), best)
    line = [chess.Move.from_uci(u) for u in played["line"]]

    # ------------------------------------------------------------ what the move does
    facts = move_facts(board, move, line)
    ideas = [_sentence(f.text) for f in facts[:4]]
    if not ideas:
        good = sorted(((v, k) for k, v in played["term_changes"].items() if v > 0), reverse=True)
        if good:
            ideas = [f"A quiet move that improves {TERM_LABELS[k].lower()} "
                     f"(+{v / 100:.2f} along the expected line)." for v, k in good[:2]]
        else:
            ideas = ["A quiet waiting move: the search found nothing better."]

    # ------------------------------------------------------------ expected continuation
    after = board.copy()
    after.push(move)
    reply_uci = played["line"][1] if len(played["line"]) > 1 else None
    reply_idea = _reply_idea(after, reply_uci)
    expected = {
        "line": _numbered_line(board, played["line"][:8]),
        "reply_san": played["line_san"][1] if len(played["line_san"]) > 1 else None,
        "reply_idea": reply_idea,
    }

    # ------------------------------------------------------------ alternatives
    alternatives = []
    for c in a["candidates"]:
        if c["move"] == report["move"]:
            continue
        diff = played["score"] - c["score"]
        alt_board = board.copy()
        alt_board.push(chess.Move.from_uci(c["move"]))
        alternatives.append({
            "san": c["san"], "score_text": c["score_text"],
            "diff": diff, "diff_text": f"{abs(diff) / 100:.2f} {'worse' if diff >= 0 else 'better'}",
            "reply_san": c.get("refutation_san"),
            "reply_idea": _reply_idea(alt_board, c.get("refutation")),
            "line": " ".join(c["line_san"][:5]),
        })

    # ------------------------------------------------------------ tempting moves refuted
    candidate_moves = {c["move"] for c in a["candidates"]}
    refuted = []
    for r in a["root_moves"]:
        if r["bound"] != "upper" or not r["refutation"] or r["move"] in candidate_moves:
            continue
        m = chess.Move.from_uci(r["move"])
        if not (board.is_capture(m) or board.gives_check(m)):
            continue
        if played["score"] - r["score"] < 100:
            continue
        san = board.san(m)
        b2 = board.copy()
        b2.push(m)
        ref = chess.Move.from_uci(r["refutation"])
        if ref not in b2.legal_moves:
            continue
        lure = "captures material" if board.is_capture(m) else "gives check"
        refuted.append({
            "san": san, "bound_text": format_score(r["score"]), "nodes": r["nodes"],
            "refutation_san": b2.san(ref), "reply_idea": _reply_idea(b2, r["refutation"]),
            "why": f"{san} {lure}, but after {b2.san(ref)} the AI proved it scores at most "
                   f"{format_score(r['score'])}, needing only {r['nodes']:,} positions.",
        })
    refuted.sort(key=lambda x: x["nodes"])
    refuted = refuted[:3]

    # ------------------------------------------------------------ evaluation terms
    eval_changes = []
    for key, delta in sorted(played["term_changes"].items(), key=lambda kv: -abs(kv[1])):
        if abs(delta) < 15 or key == "tempo":
            continue
        eval_changes.append({
            "term": key, "label": TERM_LABELS[key], "delta": delta,
            "text": f"{TERM_LABELS[key]} {'improves' if delta > 0 else 'gets worse'} by "
                    f"{abs(delta) / 100:.2f} along the expected line",
        })
    eval_changes = eval_changes[:4]

    # ------------------------------------------------------------ the search story
    s, p, roots = a["search"], a["pruning"], a["root_moves"]
    stats = s["stats"]
    story = [
        f"Minimax looked {s['depth']} half-moves ahead (the longest line reached "
        f"{s['seldepth']} half-moves, following captures and checks) and visited "
        f"{s['nodes']:,} positions in {s['seconds']:.2f} s.",
        f"Plain minimax would need about {p['minimax_nodes']:,} positions for the same depth; "
        f"this search needed 1 position for every {p['one_in']:,}. Alpha-beta itself never "
        f"changes the minimax result, and the extra pruning (null-move, reductions) only "
        f"skips lines that are very unlikely to matter.",
    ]
    if roots:
        order = next((r["order"] for r in roots if r["move"] == best["move"]), None)
        n_upper = sum(1 for r in roots if r["bound"] == "upper")
        if order == 0:
            story.append(f"Move ordering guessed right: {best['san']} was searched first, "
                         "which lets alpha-beta cut off the most.")
        elif order is not None:
            story.append(f"{best['san']} was searched as move number {order + 1}; once it was "
                         "found, the other moves had to beat it.")
        best_nodes = next((r["nodes"] for r in roots if r["move"] == best["move"]), 0)
        others = [r for r in roots if r["bound"] == "upper"]
        avg = (sum(r["nodes"] for r in others) / len(others)) if others else 0
        story.append(
            f"Of {len(roots)} legal moves, {n_upper} were proven no better than "
            f"{best['san']} with a quick 'null-window' search and cut off: on average "
            f"{avg:,.0f} positions each, against {best_nodes:,} for the best move.")
        reduced = sum(1 for r in roots if r["reduced"])
        if reduced:
            story.append(f"{reduced} moves late in the list were first searched less deeply "
                         "(late-move reductions), since good moves are usually tried early.")
    extra = []
    if stats.get("tt_cutoffs"):
        extra.append(f"reused {stats['tt_cutoffs']:,} stored results from its transposition table")
    if stats.get("null_cutoffs"):
        extra.append(f"skipped {stats['null_cutoffs']:,} branches with null-move pruning")
    if stats.get("cutoffs"):
        extra.append(f"made {stats['cutoffs']:,} alpha-beta cutoffs in total")
    if extra:
        joined = extra[0] if len(extra) == 1 else ", ".join(extra[:-1]) + " and " + extra[-1]
        story.append(f"It also {joined}.")

    depth_story = []
    prev = None
    temp = board.copy()
    for it in a.get("iterations", []):
        if not it["pv"]:
            continue
        first = chess.Move.from_uci(it["pv"][0])
        san = temp.san(first) if first in temp.legal_moves else it["pv"][0]
        if prev is None:
            depth_story.append(f"Depth {it['depth']}: first choice {san} ({it['score_text']}).")
        elif san != prev:
            depth_story.append(f"Depth {it['depth']}: changed its mind to {san} "
                               f"({it['score_text']}) after looking deeper.")
        prev = san
    if len(depth_story) == 1 and a.get("iterations"):
        last = a["iterations"][-1]
        depth_story.append(f"It kept {prev} at every depth up to {last['depth']} "
                           f"(final score {last['score_text']}).")

    choice = report.get("difficulty_choice")
    difficulty_note = None
    if choice:
        difficulty_note = (f"On this difficulty level the AI sometimes plays a weaker move on "
                           f"purpose: its best move was {choice['intended_san']}, but it played "
                           f"{choice['played_san']}.")

    return {
        "kind": "search",
        "headline": f"{report['san']}: {describe_move(board, move)}",
        "assessment": assessment(report.get("score"), ai_white),
        "ideas": ideas,
        "expected": expected,
        "alternatives": alternatives,
        "refuted": refuted,
        "eval_changes": eval_changes,
        "search": story,
        "depth_story": depth_story,
        "difficulty_note": difficulty_note,
    }
