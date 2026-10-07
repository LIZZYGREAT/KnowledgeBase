import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import middleware


def test_api_timing_header_and_slow_request_log(monkeypatch, caplog):
    times = iter([10.0, 10.125])
    monkeypatch.setattr(middleware, "perf_counter", lambda: next(times))
    application = FastAPI()
    middleware.install_api_timing(application)

    @application.get("/api/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    with TestClient(application) as client, caplog.at_level(
        logging.INFO, logger="knowledgebase.request_timing"
    ):
        response = client.get("/api/items/secret-item-id")

    assert response.headers["Server-Timing"] == "app;dur=125.0"
    assert response.json() == {"id": "secret-item-id"}
    assert "route=/api/items/{item_id}" in caplog.text
    assert "duration_ms=125.0" in caplog.text
    assert "secret-item-id" not in caplog.text


def test_non_api_request_does_not_receive_api_timing_header(monkeypatch):
    times = iter([1.0, 1.01])
    monkeypatch.setattr(middleware, "perf_counter", lambda: next(times))
    application = FastAPI()
    middleware.install_api_timing(application)

    @application.get("/health")
    async def health():
        return {"ok": True}

    with TestClient(application) as client:
        response = client.get("/health")

    assert "Server-Timing" not in response.headers
