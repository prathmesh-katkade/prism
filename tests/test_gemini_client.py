"""Tests for the google-genai SDK migration in modules.ai_analyst / modules.atlas.

Prism used to build model objects on the deprecated `google-generativeai`
package (support ended upstream — it raised a FutureWarning on every import).
This suite locks in the replacement `google-genai` Client-based plumbing:
the `_GeminiModel` adapter that keeps every call site's
`model.generate_content(contents) -> response.text` interface unchanged,
the model factories (`get_model`, `get_sql_model`, `build_model`), the
conversational `parts` shape the new SDK actually accepts, and
`call_gemini`'s error mapping for the new SDK's exception/response shapes.
"""
from __future__ import annotations

from modules import ai_analyst


class _FakeGenaiResponse:
    def __init__(self, text):
        self.text = text


class _FakeModelsAPI:
    """Stands in for `client.models` — records the last call's kwargs."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.last_call = None

    def generate_content(self, model, contents, config=None):
        self.last_call = {"model": model, "contents": contents, "config": config}
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeClient:
    def __init__(self, models_api):
        self.models = models_api


class _CodeLike(Exception):
    """Mimics google.genai.errors.APIError's `.code` (HTTP-style status int)."""

    def __init__(self, code, message="boom"):
        super().__init__(message)
        self.code = code


# ─────────────────────────────────────────────────────────────────────────
# _GeminiModel adapter
# ─────────────────────────────────────────────────────────────────────────
def test_gemini_model_adapter_forwards_model_name_and_contents():
    models_api = _FakeModelsAPI(response=_FakeGenaiResponse("hello"))
    model = ai_analyst._GeminiModel(_FakeClient(models_api), "gemini-flash-lite-latest")

    response = model.generate_content("plain prompt string")

    assert response.text == "hello"
    assert models_api.last_call["model"] == "gemini-flash-lite-latest"
    assert models_api.last_call["contents"] == "plain prompt string"


def test_gemini_model_adapter_passes_system_instruction_via_config():
    models_api = _FakeModelsAPI(response=_FakeGenaiResponse("ok"))
    model = ai_analyst._GeminiModel(
        _FakeClient(models_api), "gemini-flash-lite-latest", system_instruction="be terse"
    )

    model.generate_content("q")

    config = models_api.last_call["config"]
    assert config is not None
    assert config.system_instruction == "be terse"


def test_gemini_model_adapter_no_system_instruction_means_no_config():
    models_api = _FakeModelsAPI(response=_FakeGenaiResponse("ok"))
    model = ai_analyst._GeminiModel(_FakeClient(models_api), "gemini-flash-lite-latest")

    model.generate_content("q")

    assert models_api.last_call["config"] is None


# ─────────────────────────────────────────────────────────────────────────
# Model factories
# ─────────────────────────────────────────────────────────────────────────
def test_get_model_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(ai_analyst, "get_api_key", lambda: "")
    assert ai_analyst.get_model() is None


def test_get_model_returns_none_when_sdk_unavailable(monkeypatch):
    monkeypatch.setattr(ai_analyst, "get_api_key", lambda: "AIzaSyFAKEKEY")
    monkeypatch.setattr(ai_analyst, "genai_client", None)
    assert ai_analyst.get_model() is None


def test_get_model_builds_adapter_with_code_system_prompt(monkeypatch):
    monkeypatch.setattr(ai_analyst, "get_api_key", lambda: "AIzaSyFAKEKEY")
    model = ai_analyst.get_model()
    assert isinstance(model, ai_analyst._GeminiModel)
    assert model._model_name == ai_analyst.MODEL_NAME
    assert model._system_instruction == ai_analyst.CODE_SYSTEM_PROMPT


def test_get_sql_model_has_no_system_instruction(monkeypatch):
    monkeypatch.setattr(ai_analyst, "get_api_key", lambda: "AIzaSyFAKEKEY")
    model = ai_analyst.get_sql_model()
    assert isinstance(model, ai_analyst._GeminiModel)
    assert model._system_instruction is None


def test_build_model_lets_callers_supply_their_own_system_instruction(monkeypatch):
    monkeypatch.setattr(ai_analyst, "get_api_key", lambda: "AIzaSyFAKEKEY")
    model = ai_analyst.build_model("some-model", system_instruction="route intents")
    assert isinstance(model, ai_analyst._GeminiModel)
    assert model._model_name == "some-model"
    assert model._system_instruction == "route intents"


def test_build_model_returns_none_without_key():
    assert ai_analyst.build_model("some-model", api_key="") is None


# ─────────────────────────────────────────────────────────────────────────
# history_to_contents — new SDK requires Part dicts, not bare strings
# ─────────────────────────────────────────────────────────────────────────
def test_history_to_contents_wraps_text_in_part_dicts():
    history = [
        {"role": "user", "content": "how many rows?"},
        {"role": "assistant", "code": "result = len(df)"},
    ]
    contents = ai_analyst.history_to_contents(history)

    assert contents[0] == {"role": "user", "parts": [{"text": "how many rows?"}]}
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"] == [{"text": "```python\nresult = len(df)\n```"}]


def test_history_to_contents_handles_failed_turn():
    history = [{"role": "assistant", "ask_error": "quota exceeded"}]
    contents = ai_analyst.history_to_contents(history)
    assert contents[0]["parts"] == [{"text": "(The previous request failed and was not shown to the user.)"}]


# ─────────────────────────────────────────────────────────────────────────
# call_gemini — error mapping + empty/safety-filtered response guard
# ─────────────────────────────────────────────────────────────────────────
def test_call_gemini_maps_429_to_quota_message():
    model = _FakeGenerateContentModel(raises=_CodeLike(429))
    text, error = ai_analyst.call_gemini(model, "q")
    assert text == ""
    assert "quota" in error.lower()


def test_call_gemini_maps_403_to_auth_message():
    model = _FakeGenerateContentModel(raises=_CodeLike(403))
    text, error = ai_analyst.call_gemini(model, "q")
    assert text == ""
    assert "gemini rejected the request" in error.lower()


def test_call_gemini_falls_back_to_generic_message_for_unknown_errors():
    model = _FakeGenerateContentModel(raises=RuntimeError("network blip"))
    text, error = ai_analyst.call_gemini(model, "q")
    assert text == ""
    assert "network blip" in error


def test_call_gemini_treats_none_text_as_safety_filtered():
    # The new SDK's response.text returns None (not a raised exception) when
    # every candidate was safety-filtered or the response has no text parts.
    model = _FakeGenerateContentModel(response=_FakeGenaiResponse(None))
    text, error = ai_analyst.call_gemini(model, "q")
    assert text == ""
    assert "empty or safety-filtered" in error.lower()


def test_call_gemini_returns_text_on_success():
    model = _FakeGenerateContentModel(response=_FakeGenaiResponse("result = df.shape"))
    text, error = ai_analyst.call_gemini(model, "q")
    assert error is None
    assert text == "result = df.shape"


class _FakeGenerateContentModel:
    """A `model.generate_content(contents)`-shaped object, matching what
    real callers pass into call_gemini (either `_GeminiModel` or a test
    double) — call_gemini never touches the client SDK directly.
    """

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def generate_content(self, contents):
        if self._raises is not None:
            raise self._raises
        return self._response
