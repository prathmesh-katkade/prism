"""Tests for modules.theme — token integrity and the native-theme sync fix.

sync_native_theme() pushes theme colors into Streamlit's runtime config so
canvas-rendered widgets (st.dataframe/st.table, which CSS can't reach) track
the in-app theme toggle instead of staying stuck on .streamlit/config.toml's
hardcoded dark default. See its docstring in modules/theme.py for the full
story (found during the 2026-08-10 Phase 5 screenshot review).
"""
from __future__ import annotations

import streamlit as st

from modules.theme import DEFAULT_THEME, THEMES, sync_native_theme, theme_options

REQUIRED_TOKEN_KEYS = {
    "label", "mode", "bg", "bg_end", "surface", "surface_hover", "border",
    "text", "text_muted", "accent", "accent_rgb", "accent2", "accent2_rgb",
    "accent3", "accent3_rgb", "success", "warning", "danger", "on_accent",
    "chart_colorway",
}


def test_every_theme_has_all_required_tokens():
    for key, tokens in THEMES.items():
        missing = REQUIRED_TOKEN_KEYS - tokens.keys()
        assert not missing, f"theme '{key}' is missing tokens: {missing}"


def test_every_theme_mode_is_dark_or_light():
    for key, tokens in THEMES.items():
        assert tokens["mode"] in ("dark", "light"), f"theme '{key}' has invalid mode {tokens['mode']!r}"


def test_default_theme_key_exists_in_themes():
    assert DEFAULT_THEME in THEMES


def test_theme_options_returns_label_for_every_key():
    options = theme_options()
    assert set(options.keys()) == set(THEMES.keys())
    for key, label in options.items():
        assert label == THEMES[key]["label"]


def test_sync_native_theme_sets_base_to_light_for_arctic():
    sync_native_theme("arctic")
    assert st._config.get_option("theme.base") == "light"
    assert st._config.get_option("theme.backgroundColor") == THEMES["arctic"]["bg"]


def test_sync_native_theme_sets_base_to_dark_for_a_dark_theme():
    sync_native_theme("graphite")
    assert st._config.get_option("theme.base") == "dark"
    assert st._config.get_option("theme.backgroundColor") == THEMES["graphite"]["bg"]


def test_sync_native_theme_never_raises_even_if_the_private_api_breaks(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("private API removed in a future Streamlit version")

    monkeypatch.setattr(st._config, "set_option", _boom)
    sync_native_theme("arctic")  # must not raise
