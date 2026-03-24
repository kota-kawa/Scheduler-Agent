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


def test_get_monthly_llm_request_limit_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", raising=False)
    assert core_config.get_monthly_llm_request_limit() == 1000

    monkeypatch.setenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", "2500")
    assert core_config.get_monthly_llm_request_limit() == 2500

    monkeypatch.setenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", "0")
    assert core_config.get_monthly_llm_request_limit() == 1

    monkeypatch.setenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", "abc")
    assert core_config.get_monthly_llm_request_limit() == 1000


def test_get_max_input_chars_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("SCHEDULER_MAX_INPUT_CHARS", raising=False)
    assert core_config.get_max_input_chars() == 10000

    monkeypatch.setenv("SCHEDULER_MAX_INPUT_CHARS", "12000")
    assert core_config.get_max_input_chars() == 12000

    monkeypatch.setenv("SCHEDULER_MAX_INPUT_CHARS", "0")
    assert core_config.get_max_input_chars() == 1

    monkeypatch.setenv("SCHEDULER_MAX_INPUT_CHARS", "bad")
    assert core_config.get_max_input_chars() == 10000


def test_get_max_output_tokens_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("SCHEDULER_MAX_OUTPUT_TOKENS", raising=False)
    assert core_config.get_max_output_tokens() == 5000

    monkeypatch.setenv("SCHEDULER_MAX_OUTPUT_TOKENS", "7000")
    assert core_config.get_max_output_tokens() == 7000

    monkeypatch.setenv("SCHEDULER_MAX_OUTPUT_TOKENS", "0")
    assert core_config.get_max_output_tokens() == 1

    monkeypatch.setenv("SCHEDULER_MAX_OUTPUT_TOKENS", "oops")
    assert core_config.get_max_output_tokens() == 5000


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


def test_template_response_uses_request_first_signature(monkeypatch):
    request = _build_request()
    captured = {}

    class _DummyResponse:
        def __init__(self, context):
            self.context = context

    def _fake_template_response(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _DummyResponse(kwargs["context"])

    monkeypatch.setattr(web_templates.templates, "TemplateResponse", _fake_template_response)

    response = web_templates.template_response(request, "spa.html", {"page_id": "index"})

    assert captured["args"] == ()
    assert captured["kwargs"]["request"] is request
    assert captured["kwargs"]["name"] == "spa.html"
    assert captured["kwargs"]["context"]["request"] is request
    assert response.context["proxy_prefix"] == "/proxy"
