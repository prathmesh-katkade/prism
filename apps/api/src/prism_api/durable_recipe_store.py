"""Durable store for Clean recipes: versioned and append-only, surviving an API
restart. Mirrors the persistence pattern DurableDatasetStore and
DurableAnalyticalObjectRegistry already use against the same history database.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from prism_api_contracts import CleanRecipe, CleanRecipeStep
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)

from .durable_registry import history_database_url

_metadata = MetaData()
_recipes = Table(
    "prism_clean_recipes", _metadata,
    Column("recipe_id", String(255), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("name", String(500), nullable=False),
    Column("steps_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableRecipeStore:
    """Append-only, versioned CleanRecipe storage (no row is ever updated or
    deleted). Editing a recipe's steps writes a new version row, so analytical
    records produced by applying version N stay attributable to exactly the steps
    that existed at that version even after the recipe is edited further."""

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)

    def create(self, name: str, steps: list[CleanRecipeStep]) -> CleanRecipe:
        recipe = CleanRecipe(recipe_id=f"recipe_{uuid.uuid4().hex}", name=name, version=1, steps=steps, created_at=datetime.now(timezone.utc))
        self._insert(recipe)
        return recipe

    def new_version(self, recipe_id: str, steps: list[CleanRecipeStep]) -> CleanRecipe:
        latest = self.latest(recipe_id)
        recipe = CleanRecipe(recipe_id=recipe_id, name=latest.name, version=latest.version + 1, steps=steps, created_at=datetime.now(timezone.utc))
        self._insert(recipe)
        return recipe

    def _insert(self, recipe: CleanRecipe) -> None:
        steps_json = json.dumps([step.model_dump(mode="json") for step in recipe.steps])
        with self.engine.begin() as connection:
            connection.execute(insert(_recipes).values(
                recipe_id=recipe.recipe_id, version=recipe.version, name=recipe.name,
                steps_json=steps_json, created_at=recipe.created_at,
            ))

    def latest(self, recipe_id: str) -> CleanRecipe:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(_recipes).where(_recipes.c.recipe_id == recipe_id).order_by(_recipes.c.version.desc()).limit(1)
            ).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Recipe {recipe_id!r} was not found.")
        return _row_to_recipe(row)

    def versions(self, recipe_id: str) -> list[CleanRecipe]:
        self.latest(recipe_id)  # 404s on an unknown id before returning an empty list
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(_recipes).where(_recipes.c.recipe_id == recipe_id).order_by(_recipes.c.version.asc())
            ).mappings().all()
        return [_row_to_recipe(row) for row in rows]

    def list_latest(self) -> list[CleanRecipe]:
        with self.engine.begin() as connection:
            recipe_ids = [row[0] for row in connection.execute(select(_recipes.c.recipe_id).distinct())]
        return [self.latest(recipe_id) for recipe_id in recipe_ids]


def _row_to_recipe(row: object) -> CleanRecipe:
    mapping = dict(row)  # type: ignore[call-overload]
    steps = [CleanRecipeStep(**item) for item in json.loads(mapping["steps_json"])]
    return CleanRecipe(recipe_id=mapping["recipe_id"], name=mapping["name"], version=mapping["version"], steps=steps, created_at=mapping["created_at"])
