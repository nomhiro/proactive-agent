import json


def test_health_returns_vehicle_id():
    import function_app
    resp = function_app._health()
    assert resp.status_code == 200
    assert json.loads(resp.get_body()) == {"ok": True, "vehicle_id": "kakuu-suv"}
