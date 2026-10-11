"""Modality-separated inputs for the paired experiment."""

from sentinel.datasets import LINK


def strip_links(message: str) -> str:
    if not isinstance(message, str):
        raise ValueError("message must be text")
    return LINK.sub(" URL ", message)


def paired_inputs(kind: str, rows: list[dict], parser):
    if kind not in {"message", "url", "early"}:
        raise ValueError("unsupported paired branch")
    messages, urls = [], []
    for row in rows:
        message, url = row.get("message"), row.get("url")
        if not isinstance(message, str) or not message.strip() or not isinstance(url, str) or not url.strip():
            raise ValueError("missing paired modality")
        # Validation is deliberately required even for message-only rows.
        normalized = parser.normalize(url)
        messages.append(strip_links(message))
        urls.append(normalized.model_url)
    if kind == "message":
        return (messages,)
    if kind == "url":
        return (urls,)
    return messages, urls
