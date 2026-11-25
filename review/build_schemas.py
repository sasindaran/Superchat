"""Regenerates review/*.schema.json from src/superchat/review/contract.py. Run after editing the contract."""
import json
from pathlib import Path

from superchat.review.contract import PushPayload, ReviewList

root = Path(__file__).parent
for name, model in (("review-list", ReviewList), ("push-payload", PushPayload)):
    (root / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8")
    print("wrote", f"{name}.schema.json")
