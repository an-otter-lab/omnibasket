"""Demo mode is an explicit flag: normal mode carries no sample data."""

from fastapi.testclient import TestClient

from api.app import create_app


def _client(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("OMNIBASKET_DEMO", raising=False)
    else:
        monkeypatch.setenv("OMNIBASKET_DEMO", value)
    return TestClient(create_app())


def test_normal_mode_has_no_sample_data(monkeypatch):
    c = _client(monkeypatch, None)
    assert c.get("/config").json()["demo"] is False
    assert c.get("/sample").status_code == 404
    assert c.post("/solve").status_code == 404
    assert c.get("/events").status_code == 404
    assert c.get("/events?source=cache").status_code == 404


def test_non_truthy_values_stay_normal(monkeypatch):
    for v in ("0", "", "no", "false"):
        assert _client(monkeypatch, v).get("/config").json()["demo"] is False


def test_demo_mode_serves_sample(monkeypatch):
    for v in ("1", "true"):
        c = _client(monkeypatch, v)
        cfg = c.get("/config").json()
        assert cfg["demo"] is True and "commit" in cfg
        r = c.get("/sample")
        assert r.status_code == 200
        assert c.post("/solve").status_code == 200
