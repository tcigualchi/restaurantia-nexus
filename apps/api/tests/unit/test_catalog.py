import json

import pytest
from pydantic import ValidationError

from nexus.domain.catalog import Catalog, load_catalog


def test_catalog_loads_two_templates(catalog: Catalog) -> None:
    assert {t.key for t in catalog.templates} == {"aurora_pinheiros", "sora_moema"}


def test_scenario_override_applies_to_initial_stock(aurora) -> None:
    normal = aurora.initial_stock()
    rush = aurora.initial_stock("rush_stockout")
    assert rush["ing_costela"] < normal["ing_costela"]
    assert rush["ing_pao_brioche"] == normal["ing_pao_brioche"]


def test_unknown_ingredient_in_recipe_is_rejected(tmp_path) -> None:
    raw = json.loads(load_catalog().model_dump_json())
    raw["templates"][0]["menu_items"][0]["recipe"]["ing_inexistente"] = 1
    with pytest.raises(ValidationError, match="unknown ingredient"):
        Catalog.model_validate(raw)


def test_extra_fields_are_rejected() -> None:
    raw = json.loads(load_catalog().model_dump_json())
    raw["templates"][0]["ingredients"][0]["secret"] = "x"
    with pytest.raises(ValidationError):
        Catalog.model_validate(raw)
