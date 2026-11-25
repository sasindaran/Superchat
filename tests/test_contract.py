"""The review contract: committed JSON schemas match the models, and bad pushes are refused."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from superchat.review.contract import PushPayload, ReviewList

REVIEW = Path(__file__).resolve().parent.parent / "review"


@pytest.mark.parametrize("name,model", [("review-list", ReviewList), ("push-payload", PushPayload)])
def test_committed_schema_matches_the_models(name, model):
    committed = json.loads((REVIEW / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert committed == model.model_json_schema(), "run: python review/build_schemas.py"


def item(**over):
    base = {"keep_id": "k1", "title": "T", "decision": "D", "company": {"name": "Acme"}}
    base.update(over)
    return base


def test_minimal_valid_push():
    p = PushPayload.model_validate({"cutoff": "2026-11-25T10:00:00+00:00", "items": [item()]})
    assert p.items[0].product is None and p.items[0].kind == "decision" and p.remove_keep_ids == []


@pytest.mark.parametrize("bad", [
    item(company=None),                       # company is required
    item(company={}),
    item(company={"name": "   "}),
    item(title=""),
    item(decision="   "),
    item(kind="rumour"),
    item(product={}),                         # a product, if given, must be an id or a name
])
def test_invalid_items_are_refused(bad):
    with pytest.raises(ValidationError):
        PushPayload.model_validate({"cutoff": "x", "items": [bad]})


def test_cutoff_is_required():
    with pytest.raises(ValidationError):
        PushPayload.model_validate({"items": []})


def test_product_may_be_given_by_id_or_name_or_left_empty():
    for prod in (None, {"id": "p1"}, {"name": "Billing"}):
        PushPayload.model_validate({"cutoff": "x", "items": [item(product=prod)]})
