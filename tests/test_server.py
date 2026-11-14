"""Tests for the backend: game sessions, clock, REST API and WebSocket stream."""

import pytest
from fastapi.testclient import TestClient

from chess_ai.game import BLACK, WHITE, Game
from chess_ai.server.app import app
from chess_ai.server.sessions import LEVELS, Clock, GameSession, SessionError, SessionStore

client = TestClient(app)


def new_game(**body) -> dict:
    body.setdefault("level", "easy")
    r = client.post("/api/games", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------- sessions (no web)


def test_session_human_then_ai():
    s = GameSession(human_color=WHITE, level="easy", seed=1)
    s.human_move("e4")
    with pytest.raises(SessionError):
        s.human_move("d4")  # not your turn
    report = s.ai_move()
    assert report["ply"] == 2 and report["san"]
    assert s.game.turn == WHITE and 2 in s.reports
    st = s.state()
    assert st["ai_plies"] == [2] and len(st["evals"]) == 2
    assert st["last_ai_move"]["san"] == report["san"]


def test_ai_moves_first_when_human_is_black():
    s = GameSession(human_color=BLACK, level="beginner", seed=2)
    assert s.state()["ai_to_move"]
    report = s.ai_move()
    assert report["ply"] == 1 and report["source"] == "search"  # beginner has no book
    assert report["analysis"]["candidates"]


def test_live_iterations_are_reported():
    s = GameSession(human_color=BLACK, level="medium", seed=3)
    s.engine.book = None  # force a real search
    seen = []
    s.ai_move(on_iteration=seen.append)
    assert [d["depth"] for d in seen] == list(range(1, len(seen) + 1))
    assert seen and all(d["pv_san"] for d in seen)


def test_difficulty_choice_is_reported_honestly():
    s = GameSession(human_color=BLACK, level="beginner", seed=0)
    choices = []
    for _ in range(6):  # play a few moves; beginner sometimes picks a weaker move
        if s.game.is_over:
            break
        report = s.ai_move()
        choices.append(report["difficulty_choice"])
        if not s.game.is_over:
            s.human_move(s.game.legal_moves()[0])
    for c in choices:
        if c is not None:
            assert c["intended_san"] != c["played_san"]


def test_undo_back_to_human_turn():
    s = GameSession(human_color=WHITE, level="easy", seed=4)
    s.human_move("e4")
    s.ai_move()
    undone = s.undo()
    assert len(undone) == 2 and s.game.history == [] and s.reports == {}
    s.human_move("d4")
    assert len(s.undo()) == 1  # AI had not replied yet
    with pytest.raises(Exception):
        s.undo()  # nothing left


def test_draw_offer():
    equal = GameSession(human_color=WHITE, level="easy", fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    # bare kings is already a finished game (insufficient material)
    with pytest.raises(SessionError):
        equal.offer_draw()
    ai_winning = GameSession(human_color=WHITE, level="easy",
                             fen="3qk3/8/8/8/8/8/8/4K3 w - - 0 1")
    answer = ai_winning.offer_draw(think_time=0.2)
    assert not answer["accepted"] and answer["ai_score"] > 500
    ai_losing = GameSession(human_color=WHITE, level="easy",
                            fen="4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    assert ai_losing.offer_draw(think_time=0.2)["accepted"]
    assert ai_losing.game.status().reason == "draw_agreed"
    early_equal = GameSession(human_color=WHITE, level="easy")  # move 1: plays on
    assert not early_equal.offer_draw(think_time=0.2)["accepted"]
    late_equal = GameSession(human_color=WHITE, level="easy",
                             fen="4k3/pppp4/8/8/8/8/PPPP4/4K3 w - - 0 40")
    assert late_equal.offer_draw(think_time=0.2)["accepted"]


def test_final_position_eval_is_mate_or_draw():
    s = GameSession(human_color=WHITE, level="easy", fen="6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 30")
    s.human_move("Ra8#")
    assert s.state()["evals"] == [100000]  # White has mated


def test_unknown_level_and_colour_rejected():
    with pytest.raises(ValueError):
        GameSession(level="godlike")
    with pytest.raises(ValueError):
        GameSession(human_color="green")


def test_store_drops_oldest():
    store = SessionStore(max_sessions=2)
    a, b, c = (store.add(GameSession(level="easy")) for _ in range(3))
    assert len(store) == 2
    with pytest.raises(KeyError):
        store.get(a.id)
    assert store.get(c.id) is c


# --------------------------------------------------------------- clock


class FakeTime:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_clock_charges_time_and_increment():
    now = FakeTime()
    clock = Clock(60, increment=2, now=now)
    clock.start(WHITE)
    now.t = 10
    assert clock.left(WHITE) == 50 and clock.left(BLACK) == 60
    clock.moved(WHITE)
    assert clock.remaining[WHITE] == 52 and clock.turn == BLACK
    now.t = 25
    assert clock.left(BLACK) == 45
    assert 0.1 <= clock.budget(BLACK) < 5


def test_timeout_loses_or_draws():
    now = FakeTime()
    s = GameSession(human_color=WHITE, level="easy", clock=Clock(5, now=now))
    s.human_move("e4")
    now.t = 100  # the AI "thinks" far too long before the next request
    assert s.state()["game"]["status"]["reason"] == "timeout"
    assert s.state()["game"]["status"]["winner"] == WHITE

    g = Game("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")
    assert g.timeout(BLACK).reason == "timeout"  # White has a queen: White wins
    g = Game("4k3/8/8/8/8/8/8/4KQ2 w - - 0 1")
    assert g.timeout(WHITE).reason == "timeout_vs_insufficient_material"  # Black: bare king


# --------------------------------------------------------------- REST API


def test_health_and_info():
    assert client.get("/api/health").json()["status"] == "ok"
    info = client.get("/api/info").json()
    assert [lv["name"] for lv in info["levels"]] == list(LEVELS)
    assert "from scratch" in info["rules_engine"]


def test_full_rest_flow():
    st = new_game(human_color="white")
    gid = st["id"]
    assert st["game"]["turn"] == "white" and not st["ai_to_move"]

    r = client.post(f"/api/games/{gid}/move", json={"move": "e2e4"})
    assert r.status_code == 200 and r.json()["state"]["ai_to_move"]
    assert client.post(f"/api/games/{gid}/move", json={"move": "d4"}).status_code == 409

    r = client.post(f"/api/games/{gid}/ai-move")
    assert r.status_code == 200
    report = r.json()["report"]
    ply = report["ply"]
    assert client.get(f"/api/games/{gid}/analysis/{ply}").json()["san"] == report["san"]
    assert client.get(f"/api/games/{gid}/analysis/99").status_code == 404

    pgn = client.get(f"/api/games/{gid}/pgn").text
    assert "1. e4" in pgn and '[White "You"]' in pgn

    r = client.post(f"/api/games/{gid}/undo")
    assert r.status_code == 200 and r.json()["state"]["game"]["history"] == []

    r = client.post(f"/api/games/{gid}/resign")
    assert r.json()["state"]["game"]["status"]["reason"] == "resignation"
    assert client.post(f"/api/games/{gid}/move", json={"move": "e4"}).status_code == 409


def test_bad_requests():
    assert client.get("/api/games/nope").status_code == 404
    assert client.post("/api/games", json={"level": "godlike"}).status_code == 400
    assert client.post("/api/games", json={"fen": "bad fen"}).status_code == 400
    assert client.post("/api/games", json={"human_color": "green"}).status_code == 422
    gid = new_game()["id"]
    assert client.post(f"/api/games/{gid}/move", json={"move": "e5"}).status_code == 400
    assert client.post(f"/api/games/{gid}/ai-move").status_code == 409  # human's turn


def test_tree_endpoint():
    gid = new_game(human_color="black", level="medium",
                   fen="r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")["id"]
    assert client.get(f"/api/games/{gid}/tree").status_code == 404  # no AI move yet
    client.post(f"/api/games/{gid}/ai-move")
    t = client.get(f"/api/games/{gid}/tree", params={"depth": 2, "breadth": 3}).json()
    assert t["ply"] == 1 and t["root"]["player"] == "max" and t["visited"] > 0
    assert client.get(f"/api/games/{gid}/tree", params={"depth": 9}).status_code == 400


def test_evaluate_endpoint():
    r = client.post("/api/evaluate", json={"fen": "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"})
    assert r.status_code == 200 and r.json()["total"] > 800
    assert client.post("/api/evaluate", json={"fen": "x"}).status_code == 400


def test_new_game_with_clock_and_random_colour():
    st = new_game(human_color="random", clock_minutes=5, increment_seconds=3)
    assert st["human_color"] in ("white", "black")
    assert st["clock"]["white"] == 300 and st["clock"]["increment"] == 3


# --------------------------------------------------------------- WebSocket


def test_websocket_streams_thinking():
    gid = new_game(human_color="black", level="medium",
                   fen="r2q1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2Q1RK1 w - - 0 10")["id"]
    with client.websocket_connect(f"/ws/games/{gid}") as ws:
        ws.send_json({"type": "ai_move"})
        assert ws.receive_json()["type"] == "thinking_started"
        iterations = []
        while True:
            msg = ws.receive_json()
            if msg["type"] == "iteration":
                iterations.append(msg["data"])
            else:
                break
        assert msg["type"] == "ai_move"
        assert iterations and iterations[0]["depth"] == 1
        assert msg["state"]["game"]["turn"] == "black"
        # asking again on the human's turn is refused, but the socket stays open
        ws.send_json({"type": "ai_move"})
        assert ws.receive_json()["type"] == "thinking_started"
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "hello"})
        assert ws.receive_json()["type"] == "error"


def test_web_pages_served_without_stale_cache():
    for path in ("/", "/learn.html", "/js/learn.js", "/js/board.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache"


def test_websocket_unknown_game():
    with client.websocket_connect("/ws/games/nope") as ws:
        assert ws.receive_json()["type"] == "error"
