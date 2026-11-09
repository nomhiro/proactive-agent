from fastapi.testclient import TestClient

from proactive_web.app import Deps, create_app
from tests.helpers import MORNING, FixedClock

USER = {"X-MS-CLIENT-PRINCIPAL-NAME": "someone@example.com"}


def client(store, tmp_path=None, auth_mode="easyauth") -> TestClient:
    deps = Deps(store=store, clock=FixedClock(MORNING), auth_mode=auth_mode)
    return TestClient(create_app(deps, static_dir=tmp_path))


def test_api_requires_signed_in_user_when_auth_is_on(store):
    r = client(store).get("/api/state", params={"persona": "tanaka"})
    assert r.status_code == 401 and r.json()["detail"] == "サインインしてください"


def test_auth_off_allows_local_user(store):
    r = client(store, auth_mode="off").get("/api/me")
    assert r.status_code == 200 and r.json()["user"] == "local"


def test_state_rejects_unknown_persona(store):
    r = client(store).get("/api/state", params={"persona": "nobody"}, headers=USER)
    assert r.status_code == 400 and r.json()["detail"] == "知らない人物です"


def test_state_returns_persona_view(store):
    r = client(store).get("/api/state", params={"persona": "sato"}, headers=USER)
    assert r.status_code == 200 and r.json()["team"] == "motor_control"


def test_me_lists_four_personas_with_teams(store):
    body = client(store).get("/api/me", headers=USER).json()
    assert body["user"] == "someone@example.com"
    assert [(p["id"], p["team"]) for p in body["personas"]] == [
        ("tanaka", "integrated_control"), ("sato", "motor_control"), ("suzuki", "evaluation"),
        ("takahashi", "chief_engineer")]
    assert body["personas"][0]["name_ja"] == "田中" and body["personas"][0]["team_label"] == "車両統合制御"


def test_map_route_returns_layout(store):
    body = client(store).get("/api/map", headers=USER).json()
    assert any(n["id"] == "SIG-BrkPedalPos" for n in body["nodes"])


def test_unknown_path_serves_index_html(store, tmp_path):
    (tmp_path / "index.html").write_text("<html>画面</html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    c = client(store, tmp_path)
    assert "画面" in c.get("/foo/bar", headers=USER).text
    assert c.get("/app.js", headers=USER).text == "console.log(1)"
    assert c.get("/api/unknown", headers=USER).status_code == 404
