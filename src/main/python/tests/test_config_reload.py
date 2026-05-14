import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main.python.config.settings import settings


def test_settings_reload_updates_values_from_current_env(monkeypatch):
    original_env = os.environ.get("ENV")
    original_base_url = settings.SEARCH_API_BASE_URL

    monkeypatch.setenv("ENV", "stg")
    meta = settings.reload()

    assert meta["env"] == "stg"
    assert meta["config_path"].endswith("stg_client_search_args.yaml")
    assert settings.SEARCH_API_BASE_URL == "http://stg-search-api:8081"

    if original_env is None:
        monkeypatch.delenv("ENV", raising=False)
    else:
        monkeypatch.setenv("ENV", original_env)
    settings.reload()

    assert settings.SEARCH_API_BASE_URL == original_base_url


def test_routes_exposes_config_reload_endpoint():
    routes_file = PROJECT_ROOT / "api" / "client_search_query_parse_post.py"
    content = routes_file.read_text(encoding="utf-8")

    assert '@router.post("/config/reload"' in content
    assert "reload_runtime_components" in content
    assert "_collect_config_yaml_files" in content
    assert '"reloaded_yaml_files": reloaded_yaml_files' in content


def test_main_does_not_register_startup_reindex_hook():
    main_file = PROJECT_ROOT / "main.py"
    content = main_file.read_text(encoding="utf-8")

    assert '@app.on_event("startup")' not in content
    assert "startup_reload_runtime_config" not in content
    assert "force_reindex_fields=True" not in content


def test_reload_route_defaults_to_no_es_reindex():
    routes_file = PROJECT_ROOT / "api" / "client_search_query_parse_post.py"
    content = routes_file.read_text(encoding="utf-8")

    assert "按最新内容重载全部 YAML 配置" in content
    assert "default=False" in content
    assert "如需更新 RAG ES 索引，请手动调用 /api/v1/fields/reindex" in content
