"""Tests for Report Writer's fact-check-badge integration (Run 15).

`report_writer.build_report_content()` calls `ai_analyst.generate_key_insights()`
directly — a third Gemini call site quoting numbers straight from the data,
alongside Auto Analyst's "Run Full Analysis" (verified since Run 10) and the
AI Analyst tab's "Generate Key Insights" (verified since Run 14). The
exported HTML/PDF report is the most consequential of the three since it's a
downloadable artifact a user might hand to someone else — these tests cover
wiring modules.insight_verifier into it.
"""

from __future__ import annotations

import pandas as pd

from modules import data_engine, report_writer


class _FakeGenerateContentModel:
    """A `model.generate_content(contents)`-shaped object, matching the fake
    used across the rest of this test suite (see tests/test_gemini_client.py).
    """

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def generate_content(self, contents):
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "amount": [10, 20, 30, 40, 50] * 6,
            "segment": (["A", "B"] * 15),
        }
    )


def _quality_and_types(df: pd.DataFrame):
    column_types = data_engine.detect_column_types(df)
    quality = data_engine.get_data_quality_report(df, column_types)
    return quality, column_types


def test_build_report_content_attaches_verification_matching_findings():
    df = _sample_df()
    quality, column_types = _quality_and_types(df)
    true_mean = df["amount"].mean()  # 30.0 — a real, checkable number
    findings_text = f"1. Average amount is {true_mean:.1f}.\n2. Amount is definitely 999999 on average."
    model = _FakeGenerateContentModel(response=_FakeResponse(findings_text))

    content = report_writer.build_report_content(model, df, quality, column_types, charts={})

    assert len(content["findings"]) == 2
    verification = content["findings_verification"]
    assert verification is not None
    assert len(verification) == len(content["findings"])
    assert verification[0]["status"] == "confirmed"
    assert verification[1]["status"] == "flagged"


def test_build_report_content_verification_is_none_when_no_findings():
    df = _sample_df()
    quality, column_types = _quality_and_types(df)
    model = _FakeGenerateContentModel(raises=RuntimeError("quota exceeded"))

    content = report_writer.build_report_content(model, df, quality, column_types, charts={})

    assert content["findings"] == []
    assert content["findings_verification"] is None
    assert content["findings_error"]


def test_build_report_content_with_no_model_has_no_verification():
    df = _sample_df()
    quality, column_types = _quality_and_types(df)

    content = report_writer.build_report_content(None, df, quality, column_types, charts={})

    assert content["findings"] == []
    assert content["findings_verification"] is None


def test_html_report_embeds_verified_badge_for_confirmed_finding():
    df = _sample_df()
    quality, column_types = _quality_and_types(df)
    true_mean = df["amount"].mean()
    content = report_writer.build_report_content(
        _FakeGenerateContentModel(response=_FakeResponse(f"1. Average amount is {true_mean:.1f}.")),
        df, quality, column_types, charts={},
    )

    html = report_writer.generate_html_report(content, "test.csv")

    assert "VERIFIED" in html
    assert "Fact-checked against the data" in html


def test_html_report_embeds_unconfirmed_badge_for_flagged_finding():
    df = _sample_df()
    quality, column_types = _quality_and_types(df)
    content = report_writer.build_report_content(
        _FakeGenerateContentModel(response=_FakeResponse("1. Amount is definitely 8675309 on average.")),
        df, quality, column_types, charts={},
    )

    html = report_writer.generate_html_report(content, "test.csv")

    assert "UNCONFIRMED" in html


def test_html_report_renders_cleanly_without_verification_key():
    """Older/partial report_content dicts (or a caller that skips
    build_report_content) shouldn't crash generate_html_report — verification
    is an optional annotation, never a precondition for showing findings.
    """
    df = _sample_df()
    quality, _ = _quality_and_types(df)
    content = {
        "executive_summary": "Summary.",
        "recommendations": ["Do the thing."],
        "quality_report": quality,
        "findings": ["1. Something happened."],
        "findings_error": None,
        "chart_items": [],
        "n_rows": df.shape[0],
        "n_cols": df.shape[1],
    }

    html = report_writer.generate_html_report(content, "test.csv")

    assert "Something happened." in html
    assert "VERIFIED" not in html
    assert "UNCONFIRMED" not in html


def test_pdf_report_generates_valid_bytes_with_verification():
    df = _sample_df()
    quality, column_types = _quality_and_types(df)
    true_mean = df["amount"].mean()
    content = report_writer.build_report_content(
        _FakeGenerateContentModel(response=_FakeResponse(f"1. Average amount is {true_mean:.1f}.")),
        df, quality, column_types, charts={},
    )

    pdf_bytes = report_writer.generate_pdf_report(content, "test.csv")

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"


def test_build_findings_pdf_lines_tags_confirmed_and_flagged():
    findings = ["Average amount is 30.0.", "Amount is definitely 8675309 on average."]
    verification = [
        {"status": "confirmed", "checked": 1, "matched": 1},
        {"status": "flagged", "checked": 1, "matched": 0},
    ]

    lines = report_writer._build_findings_pdf_lines(findings, verification)

    assert len(lines) == 2
    assert "[VERIFIED]" in lines[0]
    assert "1. Average amount is 30.0." in lines[0]
    assert "[UNCONFIRMED" in lines[1]


def test_build_findings_pdf_lines_without_verification_has_no_tags():
    findings = ["Average amount is 30.0."]

    lines = report_writer._build_findings_pdf_lines(findings, None)

    assert lines == ["1. Average amount is 30.0."]


def test_verification_caption_none_when_nothing_checkable():
    verification = [{"status": "unverifiable", "checked": 0, "matched": 0}]
    assert report_writer._verification_caption(verification) is None


def test_verification_caption_none_when_verification_missing():
    assert report_writer._verification_caption(None) is None


def test_verification_caption_summarizes_confirmed_and_flagged():
    verification = [
        {"status": "confirmed", "checked": 1, "matched": 1},
        {"status": "confirmed", "checked": 1, "matched": 1},
        {"status": "flagged", "checked": 1, "matched": 0},
    ]
    caption = report_writer._verification_caption(verification)
    assert caption is not None
    assert "2 finding(s) confirmed" in caption
    assert "1 unconfirmed" in caption
