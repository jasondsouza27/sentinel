# Community scam network (prototype)

Each Sentinel detects scams on the user's own device. When it flags a message, or when the user recognises a scam and reports it, Sentinel shares only an **anonymous fingerprint** of the message, never the message itself. The hub publishes a fingerprint cluster as an active **campaign** once at least *k* distinct users have reported it. Every client downloads the published campaigns and matches incoming messages locally. Users are then warned about scams that their own model misses.

Results are in [output/research/network-v1/results.md](../output/research/network-v1/results.md).

## Components

| Module | Role |
|---|---|
| `sentinel/network/fingerprint.py` | Masks numbers and links, undoes leetspeak, look-alike letters and dotted spacing, then builds a 64-value MinHash over word 3-grams with 32 LSH bands. Adds salted domain hashes and fixed-vocabulary topic tags. |
| `sentinel/network/hub.py` | SQLite hub. Groups similar fingerprints into clusters (similarity ≥ 0.4) and publishes a cluster at ≥ *k* distinct reporters with combined weight ≥ *k*. Also handles rate limits, newcomer weight, reputation, the verified-sender allowlist, time decay and optional proof-of-work registration. |
| `sentinel/network/hub_server.py` | HTTP API: `/v1/challenge`, `/v1/register`, `/v1/reports`, `/v1/campaigns` and `/v1/stats`, plus the live dashboard. Loopback only in this prototype. |
| `sentinel/network/client.py` | Local matching against the cached feed. Reporting is off unless the user opts in, and happens in the background. |
| `sentinel/scan.py`, `analysis.py`, `server.py` | Sentinel integration. A match adds evidence and raises severity. A message Sentinel flags with high confidence is reported when sharing is on. `POST /api/community/report` handles a manual report. |
| `sentinel/network/simulate.py`, `experiments.py` | Agent-based simulation and experiment sweeps. |
| `web/network.*` | Live hub dashboard. |

## Privacy design
- **What leaves the device:** a MinHash signature, LSH band keys, salted hashes of registrable domains (never paths), topic tags from a fixed list, the category and a score bucket. No text, sender, phone number or full URL ever leaves the device.
- **What the hub stores:** those values, plus pseudonymous client IDs, counts and time stamps. There is no text column. The simulation checks this automatically: it searches the whole hub database dump for 3-word sequences from the messages.
- **Matching is local,** so the hub never learns which messages a user checks.
- **k-anonymity:** a cluster is visible only after *k* distinct reporters.
- **Residual risk:** if a message is guessable (a known template) and someone reported it by mistake, a party who already holds that text could confirm it was reported. Mistaken reports are rare (the simulation uses 0.1%), and nothing is published below *k*.

## Abuse defences

| Threat | Defence |
|---|---|
| One client sending many reports | Each client counts once per campaign, plus a per-client hourly attempt limit |
| Sybil accounts (many fake clients) | New clients count at half weight for 24 hours; optional proof-of-work at registration; reputation rises with confirmed reports |
| Poisoning a legitimate sender | A verified-sender allowlist: matching clusters are *held for review*, never published, and their reporters lose reputation |
| Harm from a wrong campaign | The network only adds a warning. It never blocks anything. |

## Run it

The two hubs below are separate. Port 8790 serves the app, and port 8791 serves the live simulation dashboard.

```bash
python3 -m sentinel.network hub --db data/network/hub.db --port 8790
```

```bash
python3 -m sentinel.network demo-seed --db data/network/hub.db
```

```bash
SENTINEL_NETWORK_HUB=http://127.0.0.1:8790 SENTINEL_NETWORK_SHARE=1 ./start-sentinel.sh
```

Open `http://127.0.0.1:8787/demo`, turn on auto-scan and press **Simulate incoming message** six times. The last three messages are modern conversational scams that the text model misses. The community network marks them.

Live simulation dashboard:

```bash
python3 -m sentinel.network hub --db data/network/sim.db --port 8791
```

```bash
.venv-text-ml/bin/python -m sentinel.network simulate --db data/network/sim.db --fresh --users 10000 --live 0.05
```

Then open `http://127.0.0.1:8791` ([screenshot](images/network-dashboard.jpg)).

Experiment sweeps (about 25 minutes): `.venv-text-ml/bin/python -m sentinel.network experiments`.

## Verification, 2026-11-05
- **Tests:** `tests/test_network.py` has 17 tests covering fingerprints, the k threshold, disputes, newcomer weight, rate limits, the allowlist and reputation, input validation, the stored schema, proof-of-work, client matching and opt-in, scan integration, the HTTP flow and a simulation smoke test.
- **Chrome 156:** a throwaway profile, unpacked extension, the server with the text model and the network on, and the demo hub seeded with three modern scams. Every demo step passed. After six incoming messages the badge showed 9: the original 4, plus 2 from the model and rules, plus 3 from the network only ([screenshot](images/network-autoscan.png)). The web app's community card showed the match ([screenshot](images/network-webapp.png)).
- **Note:** under heavy CPU load (a sweep running at the same time), the first page scan can exceed the extension's 8-second timeout. The scanner then retries after 15 seconds. An idle page scan takes about 190 ms.
