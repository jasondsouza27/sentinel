"""python -m sentinel.network {hub,simulate,experiments}"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m sentinel.network")
    sub = parser.add_subparsers(dest="command", required=True)
    hub = sub.add_parser("hub", help="Run the community hub and its live dashboard")
    hub.add_argument("--db", default=ROOT / "data/network/hub.db")
    hub.add_argument("--port", type=int, default=8790)
    hub.add_argument("--k", type=int, default=5)
    sim = sub.add_parser("simulate", help="Run one simulation (use --live with a running hub dashboard)")
    sim.add_argument("--db", default=":memory:")
    sim.add_argument("--users", type=int, default=10000)
    sim.add_argument("--k", type=int, default=5)
    sim.add_argument("--detector", choices=("model", "rates"), default="model")
    sim.add_argument("--live", type=float, default=0.0, help="Seconds to pause per simulated 10 minutes")
    sim.add_argument("--fresh", action="store_true", help="Delete the database first")
    seed = sub.add_parser("demo-seed", help="Have established demo users report a few modern scams (for live demos)")
    seed.add_argument("--db", default=ROOT / "data/network/hub.db")
    seed.add_argument("--reporters", type=int, default=9)
    exp = sub.add_parser("experiments", help="Run every experiment sweep and write output/research/network-v1")
    exp.add_argument("--users", type=int, default=10000)
    args = parser.parse_args(argv)

    if args.command == "hub":
        from .hub import Hub
        from .hub_server import create_hub_server
        server = create_hub_server(Hub(args.db, k=args.k), port=args.port)
        print(f"Community hub and dashboard at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    elif args.command == "simulate":
        from .simulate import Config, run
        if args.fresh and args.db != ":memory:":
            for suffix in ("", "-wal", "-shm"):
                Path(str(args.db) + suffix).unlink(missing_ok=True)
        result = run(Config(users=args.users, k=args.k, detector=args.detector), db_path=args.db, live_delay=args.live)
        print(json.dumps({k: result[k] for k in ("scam", "legit", "poisoning", "privacy")}, indent=1))
    elif args.command == "demo-seed":
        import time
        from .fingerprint import fingerprint
        from .hub import Hub
        from .simulate import MODERN_SCAMS
        hub = Hub(args.db)
        hub.db.execute("DELETE FROM meta WHERE key IN ('clock_hour', 'simulation')")  # back to wall-clock mode
        now = time.time() / 3600
        clients = [hub.register(now - 72) for _ in range(args.reporters)]  # established users
        for text in MODERN_SCAMS[:3]:
            for client in clients:
                hub.report(client, fingerprint(text, "user"), now)
        print(json.dumps([{k: c[k] for k in ("id", "topics", "reporters")} for c in hub.campaigns(now)], indent=1))
    else:
        from .experiments import main as experiments
        experiments(users=args.users)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
