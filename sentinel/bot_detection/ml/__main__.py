"""python -m sentinel.bot_detection.ml {prepare,train,prepare-activity,train-activity}"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m sentinel.bot_detection.ml")
    parser.add_argument("command", choices=("prepare", "train", "prepare-activity", "train-activity"))
    args = parser.parse_args(argv)
    if args.command == "prepare":
        from .source import build
        audit = build(ROOT / "data/bot-ml/raw", ROOT / "data/bot-ml")
        print(json.dumps({k: audit[k] for k in ("rows", "labels", "cross_dataset_duplicates_removed",
                                                "conflicting_label_rows_removed")}, indent=1))
    elif args.command == "train":
        from .training import train
        report = train(ROOT / "data/bot-ml", ROOT / "models/bot-ml/v1", ROOT / "output/research/bot-ml-v1")
        print(json.dumps({"lodo_mean_auc": report["leave_one_dataset_out_mean_auc"], "chosen": report["chosen_model"],
                          "release_gate": report["release_gate"]}, indent=1))
    elif args.command == "prepare-activity":
        from .activity_source import build
        audit = build(ROOT / "data/bot-ml/raw", ROOT / "data/bot-ml")
        print(json.dumps({k: audit[k] for k in ("rows", "by_subset", "excluded", "parts_without_post_history")}, indent=1))
    else:
        from .activity_training import train
        report = train(ROOT / "data/bot-ml", ROOT / "models/bot-ml/activity-v1", ROOT / "output/research/bot-ml-v1")
        print(json.dumps({k: report[k] for k in ("selection", "release_gate")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
