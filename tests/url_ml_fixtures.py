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


def sample_dataset(groups=80, rows_per_group=2, parser=None):
    from sentinel.url_ml.contracts import DatasetBundle, UrlRow
    import hashlib
    rows=[]
    for group in range(groups):
        for n in range(rows_per_group):
            label=n%2
            host=f"fixture{group}.com"
            url=f"https://{host}/" + (f"login-verify-{n}?Token=Bank" if label else f"article-{n}")
            parsed=parser.normalize(url) if parser else None
            rows.append(UrlRow(f"case-{group}-{n}",url,url,label,
                               parsed.domain_group if parsed else "domain:"+host,"synthetic"))
    manifest={"schema":"url-dataset-v1","source_sha256":"a"*64,"psl_sha256":parser.psl_sha256 if parser else "b"*64,
              "files":{"rows.jsonl":hashlib.sha256(str(rows).encode()).hexdigest()},"included_rows":len(rows)}
    return DatasetBundle(tuple(rows),manifest)
