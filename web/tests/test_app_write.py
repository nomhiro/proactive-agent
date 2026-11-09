from fastapi.testclient import TestClient
from vehicle_core.constants import VEHICLE_ID, Team

from proactive_web.app import Deps, create_app
from proactive_web.realtime import NoRealtime
from tests.helpers import MORNING, NIGHT, FixedClock, message, notification

USER = {"X-MS-CLIENT-PRINCIPAL-NAME": "someone@example.com"}
PNG = b"\x89PNG\r\n\x1a\n" + b"rest"


class RecordingRealtime:
    def __init__(self) -> None:
        self.groups = []

    def client_url(self, groups):
        self.groups.append(groups)
        return "wss://example/client?access_token=x"


class FakeFiles:
    def __init__(self) -> None:
        self.requested = []

    def content(self, file_id: str) -> bytes:
        self.requested.append(file_id)
        return PNG


def client(store, **deps) -> TestClient:
    return TestClient(create_app(Deps(store=store, clock=FixedClock(MORNING), **deps)))


def add_proposal(store):
    store.create("proposals", {
        "id": "prop-1", "vehicle_id": VEHICLE_ID, "team": "integrated_control", "kind": "impact_notice",
        "to_teams": ["motor_control"], "draft": "下書き", "related_artifact_ids": [], "thread_id": "th-1",
        "status": "pending", "decided_by": None, "decided_at": None, "created_at": NIGHT.isoformat()})


def test_decision_route_approves_and_maps_errors_to_status_and_japanese_reason(store):
    add_proposal(store)
    c = client(store)
    r = c.post("/api/proposals/prop-1/decision", json={"persona": "sato", "action": "approve"}, headers=USER)
    assert r.status_code == 403 and r.json()["detail"] == "このチームの提案ではありません"
    r = c.post("/api/proposals/prop-1/decision", json={"persona": "tanaka", "action": "approve", "draft": "直した"},
               headers=USER)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = c.post("/api/proposals/prop-1/decision", json={"persona": "tanaka", "action": "reject"}, headers=USER)
    assert r.status_code == 409
    r = c.post("/api/proposals/prop-1/decision", json={"persona": "tanaka", "action": "maybe"}, headers=USER)
    assert r.status_code == 422


def test_decision_requires_user(store):
    add_proposal(store)
    r = client(store).post("/api/proposals/prop-1/decision", json={"persona": "tanaka", "action": "approve"})
    assert r.status_code == 401


def test_settings_updates_own_team_proactivity_only(store):
    c = client(store)
    r = c.put("/api/settings", json={"persona": "suzuki", "proactivity": "important_only"}, headers=USER)
    assert r.status_code == 200 and r.json()["proactivity"] == "important_only"
    assert store.get("team_settings", "ts-evaluation")["proactivity"] == "important_only"
    assert store.get("team_settings", "ts-integrated_control")["proactivity"] == "normal"
    r = c.put("/api/settings", json={"persona": "suzuki", "proactivity": "loud"}, headers=USER)
    assert r.status_code == 422


def test_negotiate_groups_for_team_and_chief(store):
    rt = RecordingRealtime()
    c = client(store, realtime=rt)
    assert c.get("/api/negotiate", params={"persona": "tanaka"}, headers=USER).json()["url"].startswith("wss://")
    c.get("/api/negotiate", params={"persona": "takahashi"}, headers=USER)
    assert rt.groups == [["integrated_control"], [t.value for t in Team]]
    assert client(store, realtime=NoRealtime()).get(
        "/api/negotiate", params={"persona": "tanaka"}, headers=USER).json() == {"url": None}
    assert client(store).get("/api/negotiate", params={"persona": "tanaka"}, headers=USER).json() == {"url": None}


def test_file_is_served_only_when_attached_to_visible_message(store):
    store.create("messages", message("m-1", attachments=["foundry-file:file-ok"]))
    store.create("notifications", notification("n-held", delivered_at=None))
    store.create("messages", message("m-2", notification_id="n-held", attachments=["foundry-file:file-held"]))
    store.create("messages", message("m-3", team="motor_control", attachments=["foundry-file:file-mc"]))
    files = FakeFiles()
    c = client(store, files=files)
    r = c.get("/api/files/file-ok", params={"persona": "tanaka"}, headers=USER)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == PNG
    for fid in ["file-held", "file-mc", "file-unknown"]:
        assert c.get(f"/api/files/{fid}", params={"persona": "tanaka"}, headers=USER).status_code == 404
    assert files.requested == ["file-ok"]
