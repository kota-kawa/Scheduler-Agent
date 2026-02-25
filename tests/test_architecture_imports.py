import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTERS_DIR = ROOT_DIR / "scheduler_agent" / "web" / "routers"


def test_routers_do_not_import_app_module():
    for router_file in ROUTERS_DIR.glob("*_router.py"):
        source = router_file.read_text(encoding="utf-8")
        assert re.search(r"^\s*import\s+app\b", source, flags=re.MULTILINE) is None
        assert re.search(r"^\s*from\s+app\s+import\b", source, flags=re.MULTILINE) is None


def test_package_init_has_no_application_side_effect_import():
    package_init = (ROOT_DIR / "scheduler_agent" / "__init__.py").read_text(encoding="utf-8")
    assert ".application import" not in package_init


def test_asgi_entrypoint_exports_application_symbols():
    asgi_entrypoint = (ROOT_DIR / "scheduler_agent" / "asgi.py").read_text(encoding="utf-8")
    assert "from .application import app, create_app" in asgi_entrypoint


def test_app_facade_does_not_mutate_service_module_globals():
    source = (ROOT_DIR / "app.py").read_text(encoding="utf-8")
    assert "reply_service_module.UnifiedClient =" not in source
    assert "reply_service_module._content_to_text =" not in source
    assert "chat_service_module.call_scheduler_llm =" not in source
    assert "chat_service_module._build_scheduler_context =" not in source
    assert "chat_service_module._apply_actions =" not in source
