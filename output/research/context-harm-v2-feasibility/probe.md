# Reproduce the counts-only feasibility probe

Date: 2026-10-18. This is a one-off investigation command, not a production allocator or an approved study split.

Run from the active Sentinel checkout using the already installed, locked Windows CPython 3.11.17 environment. It reads the existing v1 source/reservation and prints aggregates only. It does not install packages, download source bodies, write data/artifacts, fit classifiers or score the protected test. The existing protected-pool procedure still consults protected ownership and text to enforce the established purges.

The constant-zero integer programme establishes existence under the listed count constraints. It does not balance the 70/15/15 fraction targets. Its jointly assigned calibration folds differ from v1's seeded equal-component shuffle. Neither assignment is an approved replacement protocol.

The checked-file count and manifest hash describe files present at execution time; publishing this report adds public files, so subsequent invocations will fingerprint a larger set. The report's explanatory flags were appended when documenting the raw stdout. No private membership mapping is emitted.

```powershell
$sentinelProbe = @'
import os
for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "4"
import hashlib, json, platform, time
from collections import defaultdict
from pathlib import Path
import numpy as np
import scipy
from scipy.optimize import milp, Bounds, LinearConstraint
from sentinel.context_harm.source import load_source, default_settings
from sentinel.context_harm.conversation import build_cases
from sentinel.context_harm.protocol import _protected_pool, connected_components
from sentinel.context_harm.integrity import canonical_sha256

project = Path.cwd()
root = project / "data/context-harm"
def protected_fingerprints():
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    paths += sorted(p for p in (project / "output/research").rglob("*") if p.is_file())
    paths += [project / "configs/context-harm-v1.json",
              project / "requirements-ml-win-py311.lock.txt",
              project / "requirements-url-data-win-py311.lock.txt"]
    return {p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before = protected_fingerprints()
settings = default_settings()
source = load_source(root, settings)
cohort = build_cases(source, settings)
reservation = json.loads((root / "challenge/reservation.json").read_text(encoding="utf-8"))
development, protected_test, diagnostics, audit = _protected_pool(cohort, reservation)
expected = json.loads((project / "output/research/context-harm-v1/cohort-audit.json").read_text())
assert audit["development"] == expected["development"]
assert audit["history"] == expected["history"]
del protected_test, diagnostics, cohort, source
components = connected_components(development, load_source(root, settings))
groups = defaultdict(list)
for case in development:
    groups[components[case.case_id]].append(case)
keys = sorted(groups)
vectors = np.array([[len(groups[key]),sum(c.label == 0 for c in groups[key]),sum(c.label == 1 for c in groups[key])]
                    for key in keys], dtype=int)
count = len(keys)
bins = ("train", "validation", "calibration_fold_0", "calibration_fold_1", "calibration_fold_2")
variables = count * len(bins)
matrix, lower, upper = [], [], []
def add(indices, weights, lo, hi=np.inf):
    row = np.zeros(variables)
    for destination in indices:
        row[destination * count:(destination + 1) * count] = weights
    matrix.append(row); lower.append(lo); upper.append(hi)
for index in range(count):
    row = np.zeros(variables)
    row[[destination * count + index for destination in range(5)]] = 1
    matrix.append(row); lower.append(1); upper.append(1)
for column in (1,2):
    add([0], vectors[:,column], 200)
    add([1], vectors[:,column], 30)
    add([2,3,4], vectors[:,column], 30)
    for fold in (2,3,4):
        add([fold], vectors[:,column], 5)
        add([other for other in (2,3,4) if other != fold], vectors[:,column], 20)
add([1], np.ones(count), 10)
add([2,3,4], np.ones(count), 10)
assert max(vectors[:,0]) / len(development) <= .70
A = np.asarray(matrix)
start = time.monotonic()
result = milp(c=np.zeros(variables), integrality=np.ones(variables),
              bounds=Bounds(np.zeros(variables),np.ones(variables)),
              constraints=LinearConstraint(A,np.array(lower),np.array(upper)),
              options={"time_limit":20.0,"node_limit":10000,"mip_rel_gap":0.0})
duration = time.monotonic()-start
report = {
    "schema_version":1, "date":"2026-10-18", "kind":"read_only_development_support_feasibility",
    "scope":"One zero-objective count feasibility solve; no split publication, training, predictions or test scoring",
    "python":platform.python_version(), "scipy":scipy.__version__, "numpy":np.__version__,
    "source_archive_sha256":settings["source"]["sha256"],
    "source_member_sha256":settings["source"]["member_sha256"],
    "existing_audit_sha256":hashlib.sha256((project/"output/research/context-harm-v1/cohort-audit.json").read_bytes()).hexdigest(),
    "development":audit["development"], "development_components":count,
    "largest_component_cases":int(max(vectors[:,0])),
    "minimum_class_support":{"train":200,"validation":30,"calibration":30},
    "minimum_components":{"validation":10,"calibration":10},
    "minimum_calibration_fold_class_support":{"held_out":5,"fit":20},
    "component_count_vectors_sha256":canonical_sha256({key:vectors[i].tolist() for i,key in enumerate(keys)}),
    "solver":{"objective":"constant zero; feasibility only","status":int(result.status),"success":bool(result.success),
              "message":result.message,"seconds":round(duration,6),"time_limit_seconds":20,"node_limit":10000},
    "models_trained":False, "test_scored":False, "split_published":False, "runtime_or_calibration_quality_proven":False
}
if result.x is not None:
    rounded = np.rint(result.x)
    values = A @ rounded
    valid = (np.max(np.abs(result.x-rounded)) <= 1e-6 and
             np.all(values >= np.array(lower)-1e-8) and np.all(values <= np.array(upper)+1e-8))
    report["integer_witness_verified"] = bool(valid)
    if valid:
        decisions = rounded.reshape(5,count).astype(int)
        stats = {}
        for index,name in enumerate(bins):
            totals = decisions[index] @ vectors
            stats[name] = {"cases":int(totals[0]),"class_counts":{"0":int(totals[1]),"1":int(totals[2])},
                           "components":int(decisions[index].sum())}
        cal = decisions[2:].sum(axis=0)
        totals = cal @ vectors
        stats["calibration"] = {"cases":int(totals[0]),"class_counts":{"0":int(totals[1]),"1":int(totals[2])},
                                "components":int(cal.sum())}
        report["illustrative_witness"] = stats
        report["illustrative_assignment_sha256"] = canonical_sha256({keys[i]:bins[int(np.argmax(decisions[:,i]))] for i in range(count)})
after = protected_fingerprints()
assert before == after, "A protected file changed during the read-only audit"
report["protected_files_unchanged"] = True
report["protected_files_checked"] = len(before)
report["protected_files_manifest_sha256"] = canonical_sha256(before)
print(json.dumps(report, sort_keys=True, separators=(",",":")))
'@
$sentinelProbe | & '.\.venv-url-v2-check\Scripts\python.exe' -B -u -
```

The [aggregate record](feasibility.json) contains the observed witness counts and identities. The [investigation](../../../docs/context-harm-v2-feasibility-2026-10-18.md) explains interpretation and the required review boundary.
