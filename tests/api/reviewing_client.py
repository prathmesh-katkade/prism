"""Test client adapter for legacy tests whose subject is downstream behavior.

The production API requires a real server preview ticket for every Clean apply.
Older integration tests still describe their intended mutations with one `.post`;
this adapter performs the actual preview request before posting that mutation.
Dedicated review-contract tests use plain TestClient to test rejection paths.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


class ReviewingTestClient(TestClient):
    def post(self, url: str, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        if url.startswith("/api/v1/clean/datasets/") and url.endswith("/apply"):
            preview_url = url[:-len("/apply")] + "/preview"
            if "/recipes/" in url:
                if "json" not in kwargs:
                    preview = super().post(preview_url)
                    if not preview.is_success:
                        return preview
                    kwargs["json"] = {"review_token": preview.json()["review_token"]}
            elif isinstance(kwargs.get("json"), dict) and "review_token" not in kwargs["json"]:
                preview = super().post(preview_url, json=kwargs["json"])
                if not preview.is_success:
                    return preview
                kwargs["json"] = {**kwargs["json"], "review_token": preview.json()["review_token"]}
        return super().post(url, *args, **kwargs)
