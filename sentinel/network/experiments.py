"""Experiment sweeps for the community-network simulation; writes JSON and SVG charts."""

import json
import time
from dataclasses import replace
from pathlib import Path

from .simulate import LEGIT_TEMPLATES, Config, run

OUT = Path(__file__).resolve().parents[2] / "output" / "research" / "network-v1"


def _brief(result):
    c = result["campaigns"]
    return {"model_only_protection": result["scam"]["model_only_protection"],
            "by_campaign_origin": result["scam"]["by_campaign_origin"],
            "model_plus_network_protection": result["scam"]["model_plus_network_protection"],
            "network_only_saves": result["scam"]["network_only_saves"],
            "protection_after_publication": result["scam"]["protection_after_publication"],
            "campaigns_newly_published": c["newly_published"], "campaigns_never_published": c["never_published"],
            "median_hours_to_publish": c["median_hours_to_publish"],
            "median_exposures_before_publish": c["median_exposures_before_publish"],
            "legit_false_alert_model": result["legit"]["false_alert_rate_model"],
            "legit_false_alert_network": result["legit"]["false_alert_rate_network"],
            "legit_templates_published": result["legit"]["templates_published_as_campaigns"],
            "ham_false_alert_network": result["ham"]["false_alert_rate_network"],
            "poisoning_target_published_at_end": result["poisoning"]["target_published_at_end"],
            "poisoning_target_ever_published": result["poisoning"]["target_ever_published"],
            "legit_templates_ever_published": result["legit"]["templates_ever_published"],
            "clusters": result["hub"]["clusters"], "reports": result["hub"]["reports"],
            "published_cluster_origins": result["hub"]["published_cluster_origins"],
            "privacy_passed": result["privacy"]["passed"]}


def main(users=10000, seed=7):
    OUT.mkdir(parents=True, exist_ok=True)
    base = Config(users=users, seed=seed)
    started = time.time()
    results = {}

    def go(name, config):
        t = time.time()
        result = run(config)
        results[name] = {"config": {k: v for k, v in result["config"].items() if k in
                                    ("users", "k", "share_rate", "mutation", "attackers", "defences", "detector", "user_report_rate", "model_artifact")},
                         **_brief(result), "seconds": round(time.time() - t, 1)}
        print(name, json.dumps(results[name]), flush=True)
        return result

    baseline = go("baseline_real_model", base)  # text-ml-v2 on each device
    go("real_model_v1", replace(base, model_artifact="v1"))
    go("real_model_v1_undefended", replace(base, model_artifact="v1", defences=False))
    go("real_model_no_user_reports", replace(base, user_report_rate=0.0, mistaken_report_rate=0.0))
    go("real_model_undefended", replace(base, defences=False))
    rates = go("baseline_rates_detector", replace(base, detector="rates"))
    go("rates_undefended_no_attack", replace(base, detector="rates", defences=False))
    go("rates_no_disputes", replace(base, detector="rates", dispute_rate=0.0))
    go("rates_full_allowlist", replace(base, detector="rates", allowlisted=tuple(n for n, _ in LEGIT_TEMPLATES)))
    for k in (3, 5, 10, 20):
        go(f"k_{k}", replace(base, detector="rates", k=k))
    for share in (0.1, 0.3, 0.6):
        go(f"share_{share}", replace(base, detector="rates", share_rate=share))
    go("no_mutation_rates", replace(base, detector="rates", mutation=False))
    go("no_user_reports_rates", replace(base, detector="rates", user_report_rate=0.0, mistaken_report_rate=0.0))
    for defences in (False, True):
        for attackers in (5, 10, 25, 50):
            go(f"attack_{attackers}_{'defended' if defences else 'undefended'}",
               replace(base, detector="rates", attackers=attackers, defences=defences))

    report = {"generated_seconds": round(time.time() - started, 1), "users": users, "seed": seed,
              "runs": results,
              "baseline_real_model": {k: baseline[k] for k in ("scam", "campaigns", "legit", "ham", "hub", "privacy")},
              "baseline_rates_detector": {k: rates[k] for k in ("scam", "campaigns", "legit", "ham", "hub", "privacy")}}
    for name, res in (("baseline_real_model", baseline), ("baseline_rates_detector", rates)):
        report[name]["series"] = res["series"]
    (OUT / "experiments.json").write_text(json.dumps(report, indent=1) + "\n")
    charts(report)
    return report


def _line_chart(series, title, path):
    w, h, pad = 640, 300, 44
    max_h = max(p["hour"] for p in series) or 1
    def pts(key):
        out = []
        for p in series:
            if p["scam_exposures"]:
                x = pad + (w - 2 * pad) * p["hour"] / max_h
                y = h - pad - (h - 2 * pad) * (p[key] / p["scam_exposures"])
                out.append(f"{x:.1f},{y:.1f}")
        return " ".join(out)
    grid = "".join(f'<line x1="{pad}" x2="{w-pad}" y1="{h-pad-(h-2*pad)*v:.1f}" y2="{h-pad-(h-2*pad)*v:.1f}" class="g"/>'
                   f'<text x="{pad-6}" y="{h-pad-(h-2*pad)*v+4:.1f}" class="t" text-anchor="end">{int(v*100)}%</text>'
                   for v in (0, 0.25, 0.5, 0.75, 1))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Arial" font-size="12">
<style>.g{{stroke:#e3e8e6}}.t{{fill:#5c7072}}</style><rect width="{w}" height="{h}" fill="#fff"/>
<text x="{pad}" y="22" font-weight="bold" fill="#122c31">{title}</text>{grid}
<polyline fill="none" stroke="#9aa8a6" stroke-width="2" points="{pts('model')}"/>
<polyline fill="none" stroke="#0d746e" stroke-width="2.5" points="{pts('combined')}"/>
<text x="{w-pad}" y="{h-12}" class="t" text-anchor="end">simulated hours → (0–{max_h:.0f})</text>
<rect x="{pad}" y="{h-26}" width="12" height="3" fill="#0d746e"/><text x="{pad+16}" y="{h-21}" class="t">model + network</text>
<rect x="{pad+130}" y="{h-26}" width="12" height="3" fill="#9aa8a6"/><text x="{pad+146}" y="{h-21}" class="t">model only</text>
</svg>'''
    path.write_text(svg)


def charts(report):
    _line_chart(report["baseline_rates_detector"]["series"], "Cumulative share of scam exposures protected (rates detector)",
                OUT / "protection-over-time.svg")
    _line_chart(report["baseline_real_model"]["series"], "Cumulative share of scam exposures protected (text-ml-v1)",
                OUT / "protection-over-time-real-model.svg")


if __name__ == "__main__":
    main()
