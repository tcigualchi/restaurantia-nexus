"""Synthetic restaurant catalog (templates) used by seed, simulator and forecasting.

All data here is synthetic. Templates ship inside the package (``nexus/data``) so the
API works the same in Docker, locally and as a Vercel Function, and are validated
strictly so that a typo in the dataset fails fast instead of producing silently
wrong simulations. ``DATASET_DIR`` overrides the location.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"

Unit = Literal["un", "g", "ml"]
Course = Literal["main", "side", "drink", "dessert"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IngredientTemplate(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=80)
    unit: Unit
    stock: float = Field(ge=0)
    safety_stock: float = Field(ge=0)
    unit_cost_cents: int = Field(ge=0)
    pack_size: float = Field(gt=0)
    lead_time_minutes: int = Field(ge=5, le=24 * 60)


class MenuItemTemplate(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=80)
    category: str = Field(min_length=2, max_length=40)
    course: Course
    price_cents: int = Field(gt=0)
    prep_minutes: float = Field(gt=0, le=60)
    popularity: float = Field(gt=0)
    recipe: dict[str, float]


class ScenarioOverride(_Strict):
    stock: dict[str, float] = Field(default_factory=dict)


class RestaurantTemplate(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    name: str
    timezone: str
    kitchen_lines: int = Field(ge=1, le=50)
    prep_sla_minutes: int = Field(ge=5, le=120)
    peak_orders_per_hour: float = Field(gt=0, le=600)
    history_seed: int
    ingredients: tuple[IngredientTemplate, ...]
    menu_items: tuple[MenuItemTemplate, ...]
    scenario_overrides: dict[str, ScenarioOverride] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_references(self) -> RestaurantTemplate:
        ingredient_keys = {i.key for i in self.ingredients}
        if len(ingredient_keys) != len(self.ingredients):
            raise ValueError(f"{self.key}: duplicated ingredient keys")
        item_keys = {m.key for m in self.menu_items}
        if len(item_keys) != len(self.menu_items):
            raise ValueError(f"{self.key}: duplicated menu item keys")
        for item in self.menu_items:
            if not item.recipe:
                raise ValueError(f"{self.key}: {item.key} has an empty recipe")
            for ing_key, qty in item.recipe.items():
                if ing_key not in ingredient_keys:
                    raise ValueError(f"{self.key}: {item.key} uses unknown ingredient {ing_key}")
                if qty <= 0:
                    raise ValueError(f"{self.key}: {item.key} has non-positive qty for {ing_key}")
        for scenario, override in self.scenario_overrides.items():
            for ing_key in override.stock:
                if ing_key not in ingredient_keys:
                    raise ValueError(f"{self.key}: override {scenario} uses unknown {ing_key}")
        if not any(m.course == "main" for m in self.menu_items):
            raise ValueError(f"{self.key}: at least one main course is required")
        return self

    def ingredient(self, key: str) -> IngredientTemplate:
        for ing in self.ingredients:
            if ing.key == key:
                return ing
        raise KeyError(key)

    def menu_item(self, key: str) -> MenuItemTemplate:
        for item in self.menu_items:
            if item.key == key:
                return item
        raise KeyError(key)

    def initial_stock(self, scenario_key: str | None = None) -> dict[str, float]:
        stock = {i.key: i.stock for i in self.ingredients}
        if scenario_key and scenario_key in self.scenario_overrides:
            stock.update(self.scenario_overrides[scenario_key].stock)
        return stock


class Catalog(_Strict):
    version: str
    templates: tuple[RestaurantTemplate, ...]

    def get(self, key: str) -> RestaurantTemplate:
        for template in self.templates:
            if template.key == key:
                return template
        raise KeyError(f"unknown restaurant template: {key}")


def default_dataset_dir() -> Path:
    """The synthetic catalog bundled with the package (``nexus/data``)."""
    candidate = Path(__file__).resolve().parents[1] / "data"
    if (candidate / "restaurant_templates.json").is_file():
        return candidate
    raise FileNotFoundError(f"restaurant_templates.json not found in {candidate}; set DATASET_DIR")


def load_catalog(dataset_dir: Path | None = None) -> Catalog:
    directory = dataset_dir or default_dataset_dir()
    raw = json.loads((directory / "restaurant_templates.json").read_text(encoding="utf-8"))
    raw.pop("$comment", None)
    return Catalog.model_validate(raw)


@lru_cache(maxsize=4)
def cached_catalog(dataset_dir: str | None = None) -> Catalog:
    return load_catalog(Path(dataset_dir) if dataset_dir else None)
