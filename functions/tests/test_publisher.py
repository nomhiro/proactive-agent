from vehicle_core.constants import Team

from proactive_functions.publisher import PUBLISHED_CONTAINERS, WebPubSubPublisher, publish_changes
from tests.fakes import MemoryStore, RecordingPublisher


def test_published_containers():
    assert PUBLISHED_CONTAINERS == ("messages", "proposals", "agent_runs", "notifications", "watches")


def test_message_publishes_refresh():
    store, pub = MemoryStore(), RecordingPublisher()
    doc = {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "notification_id": None}
    assert publish_changes("messages", [doc], store, pub) == 1
    assert pub.events == [("integrated_control",
                           {"type": "refresh", "kind": "messages", "id": "m1", "team": "integrated_control"})]


def test_message_of_undelivered_notification_is_held():
    store, pub = MemoryStore(), RecordingPublisher()
    store.create("notifications", {"id": "n1", "vehicle_id": "kakuu-suv", "team": "integrated_control",
                                   "delivered_at": None})
    doc = {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "notification_id": "n1"}
    assert publish_changes("messages", [doc], store, pub) == 0


def test_message_of_delivered_notification_is_sent():
    store, pub = MemoryStore(), RecordingPublisher()
    store.create("notifications", {"id": "n1", "vehicle_id": "kakuu-suv", "team": "integrated_control",
                                   "delivered_at": "2026-11-18T08:00:00+09:00"})
    doc = {"id": "m1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "notification_id": "n1"}
    assert publish_changes("messages", [doc], store, pub) == 1


def test_undelivered_notification_is_held_and_delivered_one_is_sent():
    store, pub = MemoryStore(), RecordingPublisher()
    held = {"id": "n1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "delivered_at": None}
    sent = {"id": "n2", "vehicle_id": "kakuu-suv", "team": "integrated_control",
            "delivered_at": "2026-11-18T08:00:00+09:00"}
    assert publish_changes("notifications", [held, sent], store, pub) == 1
    assert [e[1]["id"] for e in pub.events] == ["n2"]


def test_seed_and_teamless_docs_are_not_published():
    store, pub = MemoryStore(), RecordingPublisher()
    seeded = {"id": "w1", "vehicle_id": "kakuu-suv", "team": "integrated_control", "origin": "seed"}
    teamless = {"id": "w2", "vehicle_id": "kakuu-suv"}
    assert publish_changes("watches", [seeded, teamless], store, pub) == 0


def test_webpubsub_publisher_sends_to_team_group(monkeypatch):
    sent = []

    class FakeClient:
        def __init__(self, **kw):
            pass

        def send_to_group(self, group, message, content_type):
            sent.append((group, message, content_type))

    monkeypatch.setattr("proactive_functions.publisher.WebPubSubServiceClient", FakeClient)
    WebPubSubPublisher("https://x.webpubsub.azure.com", "proactive", object()).publish(
        Team.EVALUATION, {"type": "refresh"})
    assert sent == [("evaluation", {"type": "refresh"}, "application/json")]



def test_unknown_team_is_not_published():  # 最終レビューの指摘1
    store, pub = MemoryStore(), RecordingPublisher()
    doc = {"id": "w1", "vehicle_id": "kakuu-suv", "team": "nonsense"}
    assert publish_changes("watches", [doc], store, pub) == 0
