"""python -m sentinel.text_ml {prepare,train,predict}"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m sentinel.text_ml")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Verify sources, audit and split the corpus")
    prepare.add_argument("--raw", default=ROOT / "data/text-ml/raw")
    prepare.add_argument("--out", default=ROOT / "data/text-ml")
    train = sub.add_parser("train", help="Fine-tune, calibrate, evaluate once and export ONNX")
    train.add_argument("--data", default=ROOT / "data/text-ml")
    train.add_argument("--artifact", default=ROOT / "models/text-ml/v1")
    train.add_argument("--report", default=ROOT / "output/research/text-ml-v1")
    train.add_argument("--version", choices=("v1", "v2"), default="v1",
                       help="v2 adds synthetic Indian transactional ham and modern scams (run prepare-v2 first)")
    revise = sub.add_parser("revise-threshold", help="Re-choose the threshold on calibration data and re-score test")
    revise.add_argument("--data", default=ROOT / "data/text-ml")
    revise.add_argument("--artifact", default=ROOT / "models/text-ml/v1")
    revise.add_argument("--report", default=ROOT / "output/research/text-ml-v1")
    sub.add_parser("select-v2", help="Choose transformer/lexical/average for v2 on calibration data")
    sub.add_parser("prepare-v2", help="Build dataset-v2 (adds india14 English/Hinglish) and splits-v2")
    private = sub.add_parser("evaluate-private", help="Score your own redacted messages locally (CSV: text,label)")
    private.add_argument("csv")
    private.add_argument("--artifact", action="append",
                         help="Artifact folder(s) to compare (default: models/text-ml/v1 and v2 if present)")
    predict = sub.add_parser("predict", help="Assess one message with an exported artifact")
    predict.add_argument("--artifact", default=ROOT / "models/text-ml/v1")
    predict.add_argument("text")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        from . import source, splits
        audit = source.build(args.raw, args.out)
        body = splits.write(source.load_dataset(Path(args.out) / "dataset.jsonl"), Path(args.out) / "splits.json")
        print(json.dumps({"rows": audit["rows_kept"], "labels": audit["label_counts"],
                          "splits": body["summary"], "splits_sha256": body["sha256"]}, indent=1))
    elif args.command == "select-v2":
        from .training import select_ensemble
        name, summary = select_ensemble(ROOT / "data/text-ml", ROOT / "models/text-ml/v2", ROOT / "output/research/text-ml-v2")
        print(json.dumps({"chosen": name, **{k: {"threshold": v["threshold"], "test_scam_vs_ham": v["test"]["scam_vs_ham"],
                                                  "challenge": v["challenge_set"]} for k, v in summary.items()}}, indent=1))
    elif args.command == "prepare-v2":
        from . import source, splits
        audit = source.build_v2(ROOT / "data/text-ml/raw", ROOT / "data/text-ml")
        body = splits.write_v2(source.load_dataset(ROOT / "data/text-ml/dataset-v2.jsonl"),
                               ROOT / "data/text-ml/splits.json", ROOT / "data/text-ml/splits-v2.json")
        print(json.dumps({"added": audit["india14"], "splits": body["summary"]}, indent=1))
    elif args.command == "evaluate-private":
        from .private_eval import evaluate
        artifacts = args.artifact or [str(p) for p in (ROOT / "models/text-ml/v1", ROOT / "models/text-ml/v2") if p.exists()]
        print(json.dumps(evaluate(args.csv, artifacts), indent=1))
    elif args.command == "train":
        from .training import train as run
        if args.version == "v2":
            artifact = args.artifact if str(args.artifact).endswith("v2") else ROOT / "models/text-ml/v2"
            report = args.report if str(args.report).endswith("v2") else ROOT / "output/research/text-ml-v2"
            result = run(args.data, artifact, report, dataset="dataset-v2.jsonl", splits_file="splits-v2.json",
                         audit_file="audit-v2.json", version="text-ml-v2")
        else:
            result = run(args.data, args.artifact, args.report)
        print(json.dumps(result["results"], indent=1))
    elif args.command == "revise-threshold":
        from .training import revise_threshold
        print(json.dumps(revise_threshold(args.data, args.artifact, args.report)["scam_vs_ham"], indent=1))
    else:
        from .service import TextModelService
        service = TextModelService(args.artifact)
        print(json.dumps(service.assess(args.text), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
