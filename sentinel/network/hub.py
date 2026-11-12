"""Community hub: aggregates anonymous fingerprints into scam campaigns.

The hub stores signatures, LSH band keys, salted domain hashes, fixed-vocabulary
topic tags, counts and hourly time buckets. It has no column for message text,
senders or full URLs, so it cannot leak them.

A cluster is published as a campaign only when reporters with enough combined
weight flagged it, and at least `k` of them are distinct (k-anonymity). Defences
against poisoning: per-client hourly rate limits, distinct-reporter counting,
lower weight for new clients, reputation that rises when a client's reports are
confirmed and falls when they hit protected senders, and an allowlist of
verified sender templates and domains that holds matching clusters for human
review instead of publishing them. The network only adds warnings; it never
blocks anything.
"""

import hashlib
import json
import math
import secrets
import sqlite3
import threading
from pathlib import Path

from .fingerprint import BANDS, NUM_PERM, bands as band_keys, similarity

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clients (
  id TEXT PRIMARY KEY, created_hour INTEGER NOT NULL, reputation REAL NOT NULL DEFAULT 1.0);
CREATE TABLE IF NOT EXISTS clusters (
  id INTEGER PRIMARY KEY, signature TEXT NOT NULL, category TEXT, topics TEXT NOT NULL,
  domains TEXT NOT NULL, first_hour REAL NOT NULL, last_hour REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'collecting', published_hour REAL);
CREATE TABLE IF NOT EXISTS cluster_bands (band TEXT NOT NULL, cluster_id INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS cluster_bands_band ON cluster_bands(band);
CREATE TABLE IF NOT EXISTS reports (
  cluster_id INTEGER NOT NULL, client_id TEXT NOT NULL, hour REAL NOT NULL, weight REAL NOT NULL);
CREATE INDEX IF NOT EXISTS reports_cluster ON reports(cluster_id);
CREATE INDEX IF NOT EXISTS reports_client_hour ON reports(client_id, hour);
CREATE TABLE IF NOT EXISTS attempts (client_id TEXT NOT NULL, hour REAL NOT NULL);
CREATE INDEX IF NOT EXISTS attempts_client_hour ON attempts(client_id, hour);
CREATE TABLE IF NOT EXISTS disputes (cluster_id INTEGER NOT NULL, client_id TEXT NOT NULL, hour REAL NOT NULL);
CREATE TABLE IF NOT EXISTS allowlist (kind TEXT NOT NULL, value TEXT NOT NULL);
"""


class RejectedReport(ValueError):
    pass


class Hub:
    def __init__(self, db_path=":memory:", k=5, match_threshold=0.4, half_life_hours=24.0,
                 hourly_limit=20, new_client_hours=24.0, new_client_weight=0.5, pow_bits=0,
                 allowlist_threshold=0.4, dispute_ratio=0.5, disputes_enabled=True):
        self.k = k
        self.match_threshold = match_threshold
        self.half_life = half_life_hours
        self.hourly_limit = hourly_limit
        self.new_client_hours = new_client_hours
        self.new_client_weight = new_client_weight
        self.pow_bits = pow_bits
        self.allowlist_threshold = allowlist_threshold
        self.dispute_ratio = dispute_ratio
        self.disputes_enabled = disputes_enabled
        self.lock = threading.RLock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.challenge = self._meta("challenge") or self._set_meta("challenge", secrets.token_hex(8))

    # ---------- small helpers ----------
    def _meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
        return str(value)

    def set_clock(self, hour):
        """Simulation clock shown on the dashboard (real deployments use wall time)."""
        self._set_meta("clock_hour", hour)

    # ---------- clients ----------
    def register(self, hour, nonce=""):
        """Register a pseudonymous client. With pow_bits > 0 the client must find a
        nonce whose hash with the hub challenge has that many leading zero bits."""
        if self.pow_bits:
            digest = int.from_bytes(hashlib.sha256(f"{self.challenge}:{nonce}".encode()).digest(), "big")
            if digest >> (256 - self.pow_bits) != 0:
                raise RejectedReport("proof_of_work_invalid")
        client_id = secrets.token_hex(12)
        with self.lock:
            self.db.execute("INSERT INTO clients(id, created_hour) VALUES (?, ?)", (client_id, int(hour)))
        return client_id

    def solve_pow(self):
        nonce = 0
        while True:
            digest = int.from_bytes(hashlib.sha256(f"{self.challenge}:{nonce}".encode()).digest(), "big")
            if digest >> (256 - self.pow_bits) == 0:
                return str(nonce)
            nonce += 1

    # ---------- allowlist ----------
    def allow(self, fingerprint=None, domain_hash=None):
        """Protect a verified sender template (signature) or domain from publication."""
        with self.lock:
            if fingerprint:
                self.db.execute("INSERT INTO allowlist VALUES ('signature', ?)", (json.dumps(fingerprint["signature"]),))
            if domain_hash:
                self.db.execute("INSERT INTO allowlist VALUES ('domain', ?)", (domain_hash,))

    def _protected(self, signature, domain_hashes):
        for kind, value in self.db.execute("SELECT kind, value FROM allowlist"):
            if kind == "domain" and value in domain_hashes:
                return True
            if kind == "signature" and similarity(signature, json.loads(value)) >= self.allowlist_threshold:
                return True
        return False

    # ---------- reports ----------
    def _validate(self, fp):
        signature, bands = fp.get("signature"), fp.get("bands")
        if (not isinstance(signature, list) or len(signature) != NUM_PERM
                or not all(isinstance(v, int) and v >= 0 for v in signature)):
            raise RejectedReport("invalid_signature")
        if not isinstance(bands, list) or len(bands) != BANDS or not all(isinstance(b, str) and len(b) == 16 for b in bands):
            raise RejectedReport("invalid_bands")
        for field, limit in (("domains", 10), ("topics", 12)):
            values = fp.get(field, [])
            if not isinstance(values, list) or len(values) > limit or not all(isinstance(v, str) and len(v) <= 16 for v in values):
                raise RejectedReport(f"invalid_{field}")
        if fp.get("category") not in (None, "spam", "smishing", "rules", "user"):
            raise RejectedReport("invalid_category")

    def _find_cluster(self, fp):
        candidates = set()
        for band in fp["bands"]:
            candidates.update(row[0] for row in self.db.execute("SELECT cluster_id FROM cluster_bands WHERE band=?", (band,)))
        best = None
        for cluster_id in candidates:
            signature = json.loads(self.db.execute("SELECT signature FROM clusters WHERE id=?", (cluster_id,)).fetchone()[0])
            score = similarity(fp["signature"], signature)
            if score >= self.match_threshold and (best is None or score > best[1]):
                best = (cluster_id, score)
        return best[0] if best else None

    def report(self, client_id, fp, hour):
        self._validate(fp)
        with self.lock:
            client = self.db.execute("SELECT created_hour, reputation FROM clients WHERE id=?", (client_id,)).fetchone()
            if not client:
                raise RejectedReport("unknown_client")
            # Every attempt counts toward the limit, including repeats into one campaign.
            recent = self.db.execute("SELECT COUNT(*) FROM attempts WHERE client_id=? AND hour>?",
                                     (client_id, hour - 1)).fetchone()[0]
            if recent >= self.hourly_limit:
                raise RejectedReport("rate_limited")
            self.db.execute("INSERT INTO attempts VALUES (?, ?)", (client_id, hour))
            weight = client[1] * (self.new_client_weight if hour - client[0] < self.new_client_hours else 1.0)
            cluster_id = self._find_cluster(fp)
            if cluster_id is None:
                cursor = self.db.execute(
                    "INSERT INTO clusters(signature, category, topics, domains, first_hour, last_hour) VALUES (?,?,?,?,?,?)",
                    (json.dumps(fp["signature"]), fp.get("category"), json.dumps(fp.get("topics", [])),
                     json.dumps(fp.get("domains", [])), hour, hour))
                cluster_id = cursor.lastrowid
                self.db.executemany("INSERT INTO cluster_bands VALUES (?, ?)", [(b, cluster_id) for b in fp["bands"]])
            else:
                row = self.db.execute("SELECT topics, domains FROM clusters WHERE id=?", (cluster_id,)).fetchone()
                topics = sorted(set(json.loads(row[0])) | set(fp.get("topics", [])))
                domains = sorted(set(json.loads(row[1])) | set(fp.get("domains", [])))[:20]
                self.db.execute("UPDATE clusters SET last_hour=?, topics=?, domains=? WHERE id=?",
                                (hour, json.dumps(topics), json.dumps(domains), cluster_id))
            already = self.db.execute("SELECT 1 FROM reports WHERE cluster_id=? AND client_id=?",
                                      (cluster_id, client_id)).fetchone()
            if not already:  # each client counts once per campaign
                self.db.execute("INSERT INTO reports VALUES (?, ?, ?, ?)", (cluster_id, client_id, hour, weight))
            self._evaluate(cluster_id, hour)
            return cluster_id

    def dispute(self, client_id, fp, hour):
        """A user who knows a warned message is genuine says so. A published campaign
        with enough distinct disputes (relative to its reports) is withdrawn."""
        self._validate(fp)
        with self.lock:
            if not self.db.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
                raise RejectedReport("unknown_client")
            recent = self.db.execute("SELECT COUNT(*) FROM attempts WHERE client_id=? AND hour>?",
                                     (client_id, hour - 1)).fetchone()[0]
            if recent >= self.hourly_limit:
                raise RejectedReport("rate_limited")
            self.db.execute("INSERT INTO attempts VALUES (?, ?)", (client_id, hour))
            cluster_id = self._find_cluster(fp)
            if cluster_id is None or not self.disputes_enabled:
                return None
            if not self.db.execute("SELECT 1 FROM disputes WHERE cluster_id=? AND client_id=?", (cluster_id, client_id)).fetchone():
                self.db.execute("INSERT INTO disputes VALUES (?, ?, ?)", (cluster_id, client_id, hour))
            disputes = self.db.execute("SELECT COUNT(*) FROM disputes WHERE cluster_id=?", (cluster_id,)).fetchone()[0]
            reports = self.db.execute("SELECT COUNT(*) FROM reports WHERE cluster_id=?", (cluster_id,)).fetchone()[0]
            status = self.db.execute("SELECT status FROM clusters WHERE id=?", (cluster_id,)).fetchone()[0]
            if status == "published" and disputes >= max(self.k, self.dispute_ratio * reports):
                self.db.execute("UPDATE clusters SET status='disputed' WHERE id=?", (cluster_id,))
                self.db.execute("UPDATE clients SET reputation=MAX(reputation-0.2, 0.0) WHERE id IN "
                                "(SELECT client_id FROM reports WHERE cluster_id=?)", (cluster_id,))
            return cluster_id

    def _weight(self, cluster_id, hour):
        rows = self.db.execute("SELECT hour, weight FROM reports WHERE cluster_id=?", (cluster_id,)).fetchall()
        decayed = sum(w * math.pow(0.5, max(hour - h, 0) / self.half_life) for h, w in rows)
        return len(rows), decayed

    def _evaluate(self, cluster_id, hour):
        status, signature, domains = self.db.execute(
            "SELECT status, signature, domains FROM clusters WHERE id=?", (cluster_id,)).fetchone()
        if status != "collecting":  # published, held or disputed clusters are final until reviewed
            return
        # Publication uses raw weight; decay only ages campaigns out of the feed.
        distinct, weight = self.db.execute("SELECT COUNT(*), COALESCE(SUM(weight), 0) FROM reports WHERE cluster_id=?",
                                           (cluster_id,)).fetchone()
        if distinct < self.k or weight < self.k - 1e-9:
            return
        if self._protected(json.loads(signature), set(json.loads(domains))):
            self.db.execute("UPDATE clusters SET status='held_for_review' WHERE id=?", (cluster_id,))
            # Reporters of a protected sender lose reputation (possible poisoning).
            self.db.execute("UPDATE clients SET reputation=MAX(reputation-0.5, 0.0) WHERE id IN "
                            "(SELECT client_id FROM reports WHERE cluster_id=?)", (cluster_id,))
            return
        self.db.execute("UPDATE clusters SET status='published', published_hour=? WHERE id=?", (hour, cluster_id))
        self.db.execute("UPDATE clients SET reputation=MIN(reputation+0.1, 2.0) WHERE id IN "
                        "(SELECT client_id FROM reports WHERE cluster_id=?)", (cluster_id,))

    # ---------- feed ----------
    def campaigns(self, hour, active_hours=72):
        """Published campaigns seen within `active_hours`, newest first. No text."""
        out = []
        with self.lock:
            rows = self.db.execute(
                "SELECT id, signature, category, topics, domains, first_hour, last_hour, published_hour FROM clusters "
                "WHERE status='published' AND last_hour>=? ORDER BY last_hour DESC", (hour - active_hours,)).fetchall()
            for cid, signature, category, topics, domains, first, last, published in rows:
                distinct, weight = self._weight(cid, hour)
                signature = json.loads(signature)
                out.append({"id": cid, "signature": signature,
                            "bands": band_keys(signature),
                            "category": category, "topics": json.loads(topics), "domains": json.loads(domains),
                            "reporters": distinct, "confidence": round(weight, 2),
                            "first_hour": first, "last_hour": last, "published_hour": published})
        return out

    def stats(self, hour=None):
        with self.lock:
            hour = float(self._meta("clock_hour") or 0) if hour is None else hour
            count = lambda sql: self.db.execute(sql).fetchone()[0]
            by_status = dict(self.db.execute("SELECT status, COUNT(*) FROM clusters GROUP BY status").fetchall())
            per_hour = self.db.execute("SELECT CAST(hour AS INTEGER), COUNT(*) FROM reports GROUP BY 1 ORDER BY 1").fetchall()
            sim = self._meta("simulation")
        return {"clock_hour": hour, "clients": count("SELECT COUNT(*) FROM clients"),
                "reports": count("SELECT COUNT(*) FROM reports"), "clusters": by_status,
                "reports_per_hour": per_hour, "k": self.k, "simulation": json.loads(sim) if sim else None}

    def stored_columns(self):
        """Every stored column, for the privacy audit."""
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: [c[1] for c in self.db.execute(f"PRAGMA table_info({t})")] for t in tables}
