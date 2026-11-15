import json

from .catalog import REPLAYS
from .config import ROOT


async def train_round(engine, run, checkpoint):
    labels = json.loads((ROOT / "data" / "training.json").read_text())
    bookmark = None
    added = 0
    for case_id, expected in labels.items():
        case = REPLAYS[case_id]
        if case["split"] != "train":
            raise ValueError("Training labels contain a held-out replay")
        if case["batch"] == checkpoint:
            bookmark = await engine.verify_feedback(
                run, case, expected["service"], expected["tool"]
            )
            added += 1
    return added, bookmark
