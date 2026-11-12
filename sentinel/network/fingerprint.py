"""Privacy-preserving scam-campaign fingerprints.

A fingerprint describes a message's *template* without containing its text:

- `signature`: a 64-value MinHash over word shingles of the masked template
  (numbers, links and phone numbers replaced). Reworded variants of one scam
  share many values, so similarity survives small edits.
- `bands`: locality-sensitive hashing keys (32 bands x 2 rows) used to find
  candidate matches quickly.
- `domains`: salted hashes of registrable link domains (never paths).
- `topics`: tags from a fixed vocabulary (for example "kyc", "prize"), so the
  hub can label campaigns without seeing any free text.

Nothing in a fingerprint can be turned back into the message.
"""

import hashlib
import re
import unicodedata

from ..text_ml.source import template_key

NUM_PERM = 64
BANDS = 32
ROWS = NUM_PERM // BANDS
PRIME = (1 << 61) - 1
DOMAIN_SALT = b"sentinel-network-v1"
# Fixed seeds: every client must compute identical signatures.
_PARAMS = []
for i in range(NUM_PERM):
    digest = hashlib.blake2b(f"sentinel-minhash-{i}".encode(), digest_size=16).digest()
    _PARAMS.append((int.from_bytes(digest[:8], "big") % (PRIME - 1) + 1, int.from_bytes(digest[8:], "big") % PRIME))

TOPICS = {
    "kyc": ("kyc", "pan", "aadhaar", "verify your account", "account suspended", "account blocked", "update your details"),
    "bank": ("bank", "card", "a/c", "account", "debit", "credit", "upi", "transaction"),
    "otp": ("otp", "one-time password", "one time password", "verification code", "password"),
    "prize": ("won", "winner", "prize", "reward", "lottery", "congratulations", "claim", "free"),
    "job": ("job", "hiring", "selected", "salary", "work from home", "registration fee", "interview", "role"),
    "delivery": ("parcel", "delivery", "courier", "shipment", "package", "redelivery", "customs"),
    "payment": ("pay", "fee", "payment", "refund", "transfer", "send money", "charge", "gpay", "phonepe", "paytm", "send me"),
    "authority": ("police", "cyber crime", "officer", "inspector", "arrest", "detained", "customs", "court", "cbi"),
    "impersonation": ("new number", "lost my phone", "its me", "it's me", "your son", "your daughter"),
    "investment": ("trading", "profit", "crypto", "stock", "returns", "investment", "tips"),
    "urgency": ("urgent", "immediately", "within", "expire", "today", "last chance", "act now"),
    "subscription": ("subscribe", "unsubscribe", "stop", "txt", "text", "reply"),
}
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b(?:[a-z0-9-]+\.)+(?:com|net|org|in|co|io|info|biz|xyz|top|ly|me|edu|gov|example|test)\b[^\s<>\"']*",
                 re.IGNORECASE)
SECOND_LEVEL = {"co.uk", "ac.in", "co.in", "gov.in", "org.in", "com.au", "co.jp", "ac.uk", "net.in"}


def _fold(text):
    """Undo common disguises so leetspeak and look-alike letters fingerprint alike."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"а": "a", "е": "e", "о": "o", "с": "c", "р": "p",
                                         "х": "x", "і": "i"}))
    # Dotted spacing (f.r.e.e) -> free; leave real abbreviations of 1-2 letters alone.
    text = re.sub(r"\b(?:[A-Za-z]\.){2,}[A-Za-z]\b", lambda m: m.group(0).replace(".", ""), text)
    # Digits used as letters inside words (fr33, c1aim).
    return re.sub(r"\b\w*[A-Za-z]\w*\b", lambda m: m.group(0).translate(str.maketrans("43015", "aeois")), text)


def shingles(text, size=3):
    words = template_key(_fold(text)).split()
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def minhash(items):
    if not items:
        return None
    bases = [int.from_bytes(hashlib.blake2b(item.encode(), digest_size=8).digest(), "big") for item in items]
    return [min((a * x + b) % PRIME for x in bases) for a, b in _PARAMS]


def bands(signature):
    return [hashlib.blake2b(f"{band}:{signature[band * ROWS:(band + 1) * ROWS]}".encode(), digest_size=8).hexdigest()
            for band in range(BANDS)]


def similarity(first, second):
    """Estimated Jaccard similarity of two signatures."""
    return sum(a == b for a, b in zip(first, second)) / NUM_PERM


def registrable_domain(host):
    host = host.lower().strip(".").removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def domains(text):
    found = set()
    for match in URL.finditer(text):
        raw = re.sub(r"^(?:https?://)", "", match.group(0), flags=re.IGNORECASE)
        host = re.split(r"[/?#:]", raw, maxsplit=1)[0]
        if "." in host:
            found.add(hashlib.sha256(DOMAIN_SALT + registrable_domain(host).encode()).hexdigest()[:16])
    return sorted(found)


def topics(text):
    lower = _fold(text).lower()
    return sorted(name for name, words in TOPICS.items()
                  if any(re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", lower) for word in words))


def fingerprint(text, category=None, score=None):
    """Fingerprint of one message, or None when it has too little text to describe."""
    signature = minhash(shingles(text))
    if signature is None:
        return None
    result = {"version": 1, "signature": signature, "bands": bands(signature),
              "domains": domains(text), "topics": topics(text)}
    if category:
        result["category"] = category
    if score is not None:
        result["score_bucket"] = min(int(score * 10), 9) / 10
    return result
