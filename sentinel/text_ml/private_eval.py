"""Score a private, locally held CSV of real messages (columns: text,label with
label ham or scam). Nothing is uploaded or saved; only aggregate counts and the
indices of mistakes are printed, never message text."""

import csv
from pathlib import Path

from .service import TextModelService


def evaluate(csv_path, artifacts):
    rows = []
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            label = (row.get("label") or "").strip().lower()
            text = (row.get("text") or "").strip()
            if label in ("ham", "scam") and text:
                rows.append((text, label))
    if not rows:
        raise ValueError("No rows with text and a ham/scam label")
    report = {"rows": len(rows), "ham": sum(l == "ham" for _, l in rows), "scam": sum(l == "scam" for _, l in rows)}
    for artifact in artifacts:
        service = TextModelService(artifact)
        if not service.available:
            report[str(artifact)] = {"error": service.error}
            continue
        flagged = [p["flagged"] for p in service.predict([t for t, _ in rows])]
        wrong = [i for i, ((_, label), f) in enumerate(zip(rows, flagged)) if f != (label == "scam")]
        ham_flags = sum(f for (_, l), f in zip(rows, flagged) if l == "ham")
        scam_flags = sum(f for (_, l), f in zip(rows, flagged) if l == "scam")
        report[service.manifest["model_version"]] = {
            "genuine_false_alarms": f"{ham_flags}/{report['ham']}", "scams_caught": f"{scam_flags}/{report['scam']}",
            "mistake_row_numbers": [i + 2 for i in wrong]}  # CSV line numbers, header is line 1
    return report
