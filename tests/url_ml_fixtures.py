"""Synthetic URL fixtures; never evidence of real detector quality."""

import importlib.util
from pathlib import Path

HAS_ML = all(importlib.util.find_spec(name) for name in ("numpy", "sklearn", "idna", "tldextract", "psutil"))


def fixture_psl(directory: Path) -> Path:
    path = directory / "suffix.dat"
    path.write_text(
        "// Synthetic test suffixes, not a production PSL.\n"
        "// ===BEGIN ICANN DOMAINS===\ncom\norg\nde\nuk\nco.uk\nexample\n"
        "// ===END ICANN DOMAINS===\n"
        "// ===BEGIN PRIVATE DOMAINS===\ngithub.io\n"
        "// ===END PRIVATE DOMAINS===\n", encoding="utf-8",
    )
    return path
