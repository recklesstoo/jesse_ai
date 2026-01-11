from pathlib import Path

from hypothesis import given, strategies as st


def _proxy_prefixes():
    config = Path("frontend/vite.config.js").read_text(encoding="utf-8")
    prefixes = []
    for needle in ('"/api"', '"/ws"'):
        if needle in config:
            prefixes.append(needle.strip('"'))
    return config, prefixes


def test_vite_proxy_config_present():
    config, prefixes = _proxy_prefixes()
    assert "/api" in prefixes
    assert "/ws" in prefixes
    assert "127.0.0.1:8000" in config
    assert "ws://127.0.0.1:8000" in config


@given(suffix=st.text(min_size=0, max_size=20, alphabet=st.characters(min_codepoint=32, max_codepoint=126)))
def test_proxy_transparency_for_api_paths(suffix):
    config, prefixes = _proxy_prefixes()
    assert "rewrite" not in config
    for prefix in prefixes:
        path = f"{prefix}/{suffix}".replace("//", "/")
        assert path.startswith(prefix)
