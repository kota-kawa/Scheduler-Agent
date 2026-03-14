from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from scheduler_agent.core import config as core_config
from scheduler_agent.web import templates as web_templates


def _build_request():
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(core_config.BASE_DIR / "static")), name="static")

    @app.get("/", name="index")
    def _index():
        return {"ok": True}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"x-forwarded-prefix", b"/proxy")],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "app": app,
        "router": app.router,
        "session": {},
    }
    return Request(scope)


def test_get_max_action_rounds_clamps_values(monkeypatch):
    monkeypatch.setenv("SCHEDULER_MAX_ACTION_ROUNDS", "999")
    assert core_config.get_max_action_rounds() == 10

    monkeypatch.setenv("SCHEDULER_MAX_ACTION_ROUNDS", "0")
    assert core_config.get_max_action_rounds() == 1

    monkeypatch.setenv("SCHEDULER_MAX_ACTION_ROUNDS", "abc")
    assert core_config.get_max_action_rounds() == 10


def test_get_max_same_read_action_streak_clamps_values(monkeypatch):
    monkeypatch.setenv("SCHEDULER_MAX_SAME_READ_ACTION_STREAK", "999")
    assert core_config.get_max_same_read_action_streak() == 10

    monkeypatch.setenv("SCHEDULER_MAX_SAME_READ_ACTION_STREAK", "-5")
    assert core_config.get_max_same_read_action_streak() == 1

    monkeypatch.setenv("SCHEDULER_MAX_SAME_READ_ACTION_STREAK", "oops")
    assert core_config.get_max_same_read_action_streak() == 10


def test_flash_and_pop_round_trip():
    request = _build_request()

    web_templates.flash(request, "saved")
    web_templates.flash(request, "updated")

    assert web_templates.pop_flashed_messages(request) == ["saved", "updated"]
    assert web_templates.pop_flashed_messages(request) == []


def test_template_response_applies_proxy_prefix():
    request = _build_request()

    response = web_templates.template_response(request, "spa.html", {"page_id": "index"})
    body = response.body.decode("utf-8")

    assert response.context["proxy_prefix"] == "/proxy"
    assert response.context["url_for"]("index") == "/proxy/"
    assert 'meta name="proxy-prefix" content="/proxy"' in body
    assert "/proxy/static/spa/app.css" in body
