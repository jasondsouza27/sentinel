"""Sentinel's side of the community network.

- `match(text)` compares a message with the locally cached campaign feed. The
  hub never learns which messages were checked.
- `report(text, ...)` sends only a fingerprint, and only when the user turned on
  sharing and Sentinel itself flagged the message.
Network failures never break a check: the client falls back to its last feed.
"""

import json
import queue
import threading
import time
import urllib.request
from pathlib import Path

from .fingerprint import fingerprint, similarity


class LocalTransport:
    """In-process hub (simulation and tests)."""

    def __init__(self, hub, clock):
        self.hub, self.clock = hub, clock

    def register(self):
        nonce = self.hub.solve_pow() if self.hub.pow_bits else ""
        return self.hub.register(self.clock(), nonce)

    def report(self, client_id, fp):
        return self.hub.report(client_id, fp, self.clock())

    def campaigns(self):
        return self.hub.campaigns(self.clock())

    def dispute(self, client_id, fp):
        return self.hub.dispute(client_id, fp, self.clock())


class HttpTransport:
    def __init__(self, base_url, timeout=3.0):
        self.base, self.timeout = base_url.rstrip("/"), timeout

    def _call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def register(self):
        challenge = self._call("/v1/challenge")
        nonce = ""
        if challenge["pow_bits"]:
            import hashlib
            n = 0
            while int.from_bytes(hashlib.sha256(f"{challenge['challenge']}:{n}".encode()).digest(), "big") >> (256 - challenge["pow_bits"]):
                n += 1
            nonce = str(n)
        return self._call("/v1/register", {"nonce": nonce})["client_id"]

    def report(self, client_id, fp):
        return self._call("/v1/reports", {"client_id": client_id, "fingerprint": fp})

    def campaigns(self):
        return self._call("/v1/campaigns")["campaigns"]

    def dispute(self, client_id, fp):
        return self._call("/v1/disputes", {"client_id": client_id, "fingerprint": fp})


class NetworkClient:
    def __init__(self, transport, share=False, state_path=None, match_threshold=0.4):
        self.transport = transport
        self.share = share
        self.state_path = Path(state_path) if state_path else None
        self.match_threshold = match_threshold
        self.client_id = None
        self.feed, self.index = [], {}
        self.synced_at = None
        self.error = None
        self.lock = threading.Lock()
        if self.state_path and self.state_path.exists():
            self.client_id = json.loads(self.state_path.read_text()).get("client_id")

    # ---------- feed ----------
    def sync(self):
        try:
            feed = self.transport.campaigns()
        except Exception as error:  # keep the last good feed
            self.error = type(error).__name__
            return False
        index = {}
        for campaign in feed:
            for band in campaign["bands"]:
                index.setdefault(band, []).append(campaign)
        with self.lock:
            self.feed, self.index, self.synced_at, self.error = feed, index, time.time(), None
        return True

    def match(self, text, fp=None):
        fp = fp or fingerprint(text)
        if fp is None:
            return None
        with self.lock:
            candidates = {id(c): c for band in fp["bands"] for c in self.index.get(band, [])}
        best = None
        for campaign in candidates.values():
            score = similarity(fp["signature"], campaign["signature"])
            if score >= self.match_threshold and (best is None or score > best[1]):
                best = (campaign, score)
        if not best:
            return None
        campaign, score = best
        return {"campaign_id": campaign["id"], "similarity": round(score, 3), "reporters": campaign["reporters"],
                "topics": campaign["topics"], "category": campaign["category"],
                "first_hour": campaign["first_hour"], "last_hour": campaign["last_hour"]}

    # ---------- reporting ----------
    def _ensure_registered(self):
        if self.client_id is None:
            self.client_id = self.transport.register()
            if self.state_path:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                self.state_path.write_text(json.dumps({"client_id": self.client_id}))
        return self.client_id

    def report(self, text, category, score):
        """Send a fingerprint (never text). Returns the hub's reply or None."""
        if not self.share:
            return None
        fp = fingerprint(text, category, score)
        if fp is None:
            return None
        return self.transport.report(self._ensure_registered(), fp)

    def dispute(self, text):
        """The user knows a warned message is genuine (only with sharing on)."""
        if not self.share:
            return None
        fp = fingerprint(text)
        return None if fp is None else self.transport.dispute(self._ensure_registered(), fp)

    def report_manual(self, text):
        """The user recognised a scam Sentinel did not flag; share its fingerprint."""
        return self.report(text, "user", None)

    def health(self):
        return {"state": "ready" if self.synced_at else "unavailable", "sharing": self.share,
                "campaigns": len(self.feed), "error": self.error}


class BackgroundNetwork:
    """Wraps a client for the live app: syncs periodically, reports off the request path."""

    def __init__(self, client, sync_seconds=30):
        self.client = client
        self.reports = queue.Queue(maxsize=200)
        self.sync_seconds = sync_seconds
        threading.Thread(target=self._sync_loop, daemon=True).start()
        threading.Thread(target=self._report_loop, daemon=True).start()

    def _sync_loop(self):
        while True:
            self.client.sync()
            time.sleep(self.sync_seconds)

    def _report_loop(self):
        while True:
            text, category, score = self.reports.get()
            try:
                self.client.report(text, category, score)
            except Exception:
                pass

    def match(self, text):
        return self.client.match(text)

    def report(self, text, category, score):
        if self.client.share:
            try:
                self.reports.put_nowait((text, category, score))
            except queue.Full:
                pass

    def report_manual(self, text):
        self.report(text, "user", None)
        return self.client.share

    def health(self):
        return self.client.health()
