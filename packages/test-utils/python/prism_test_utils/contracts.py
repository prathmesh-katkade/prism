from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def assert_model_payload(model: type[ModelT], payload: dict[str, Any]) -> ModelT:
    """Validate a public payload and return the typed contract instance."""
    return model.model_validate(payload)
