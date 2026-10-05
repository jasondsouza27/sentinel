"""Bounded CPU factories and one isolated process per candidate fit."""
import hashlib
import itertools
import json
import multiprocessing
import os
import random
import time
from collections import defaultdict
from pathlib import Path
from .contracts import DatasetError

def build_pipeline(branch,params,parser):
    import numpy as np
    from sklearn.pipeline import Pipeline
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from .features import CanonicalTransformer,LexicalTransformer
    if branch=="char_tfidf":
        return Pipeline([("canonical",CanonicalTransformer(parser)),
          ("tfidf",TfidfVectorizer(analyzer="char",ngram_range=(3,5),lowercase=False,dtype=np.float32,
                                   max_features=params.get("max_features",50000))),
          ("classifier",LogisticRegression(C=params.get("C",1),class_weight=params.get("class_weight"),
                                           solver="liblinear",max_iter=1000,random_state=42))])
    if branch=="lexical_hgb":
        return Pipeline([("lexical",LexicalTransformer(parser)),
          ("classifier",HistGradientBoostingClassifier(max_depth=params.get("max_depth",3),
                  learning_rate=params.get("learning_rate",.1),max_iter=params.get("max_iter",200),
                  early_stopping=False,random_state=42))])
    raise DatasetError("unknown_model_branch")

def fit_pipeline(rows,branch,params,parser):
    from threadpoolctl import threadpool_limits
    model=build_pipeline(branch,params,parser)
    with threadpool_limits(limits=4): model.fit([r.url for r in rows],[r.label for r in rows])
    return model

def raw_scores(model,urls):
    import numpy as np
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=4): probabilities=model.predict_proba(urls)
    classes=list(model.classes_)
    if 1 not in classes: raise DatasetError("positive_class_missing")
    scores=np.asarray(probabilities[:,classes.index(1)],dtype=float)
    if not np.all(np.isfinite(scores)) or np.any((scores<0)|(scores>1)): raise DatasetError("invalid_model_scores")
    return scores

def candidate_grid(config):
    char=config["char_tfidf"]; lexical=config["lexical_hgb"]
    grid=[("char_tfidf",{"C":c,"class_weight":w,"max_features":char["max_features"]})
          for c,w in itertools.product(char["C"],char["class_weight"])]
    grid += [("lexical_hgb",{"max_depth":d,"learning_rate":lr,"max_iter":lexical["max_iter"]})
             for d,lr in itertools.product(lexical["max_depth"],lexical["learning_rate"])]
    if any(sum(b==branch for b,p in grid)>6 for branch in ("char_tfidf","lexical_hgb")):
        raise DatasetError("candidate_budget_exceeded")
    return grid

def _fit_worker(connection,rows,branch,params,parser,native_threads):
    import psutil
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    from threadpoolctl import threadpool_limits
    started=time.perf_counter()
    try:
        with warnings.catch_warnings(record=True) as captured,threadpool_limits(limits=native_threads):
            warnings.simplefilter("always",ConvergenceWarning)
            model=fit_pipeline(rows,branch,params,parser)
        info=psutil.Process().memory_info()
        peak=getattr(info,"peak_rss",None) or getattr(info,"peak_wset",None)
        if peak is None: raise DatasetError("peak_memory_field_unavailable")
        convergence=any(issubclass(w.category,ConvergenceWarning) for w in captured)
        record={"status":"convergence_failure" if convergence else "ok","pid":os.getpid(),
                "peak_bytes":int(peak),"fit_seconds":time.perf_counter()-started,"native_threads":native_threads,
                "branch":branch,"params":params,"train_rows":len(rows)}
        connection.send((None if convergence else model,record))
    except Exception as error:
        connection.send((None,{"status":"fit_failed","error":getattr(error,"reason",type(error).__name__),
                              "branch":branch,"params":params,"fit_seconds":time.perf_counter()-started}))
    finally: connection.close()

def fit_candidate(rows,branch,params,parser,native_threads=4,max_peak_bytes=8*1024**3):
    import psutil
    ctx=multiprocessing.get_context("spawn"); receiving,sending=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_fit_worker,args=(sending,rows,branch,params,parser,native_threads))
    keys=("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS")
    previous={key:os.environ.get(key) for key in keys}
    try:
        for key in keys: os.environ[key]=str(native_threads)
        process.start()
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value
    sending.close(); record=None; result=None
    try:
        while True:
            if receiving.poll(.2):
                try: result,record=receiving.recv()
                except EOFError: record={"status":"worker_exited","branch":branch,"params":params}
                break
            if not process.is_alive():
                record={"status":"worker_exited","branch":branch,"params":params,"exit_code":process.exitcode}; break
            try:
                if psutil.Process(process.pid).memory_info().rss>max_peak_bytes:
                    process.terminate(); record={"status":"memory_budget_exceeded","branch":branch,"params":params}; break
            except psutil.NoSuchProcess: pass
        process.join(timeout=5)
        if process.is_alive(): process.terminate(); process.join()
        if record.get("peak_bytes",0)>max_peak_bytes:
            record["status"]="memory_budget_exceeded"; result=None
        return result,record
    finally:
        receiving.close()
        if process.is_alive(): process.terminate(); process.join()
        process.close()

def pilot_rows(splits,maximum=2000,seed=42):
    groups=defaultdict(list)
    for row in splits.partitions["train"]: groups[row.domain_group].append(row)
    keys=sorted(groups); random.Random(seed).shuffle(keys); selected=[]
    for key in keys:
        if len(selected)+len(groups[key])<=maximum: selected.extend(groups[key])
    if not selected or {r.label for r in selected}!={0,1}: raise DatasetError("pilot_insufficient_classes_or_group_budget")
    return tuple(selected)

def rule_predictions(rows):
    from sentinel.analysis import analyze
    return [int(bool(analyze({"url":r.url})["fraud"]["evidence"])) for r in rows]

def resource_pilot(splits,config,parser):
    rows=pilot_rows(splits,config["pilot_max_rows"],config["seed"])
    ids=[r.case_id for r in rows]; measurements=[]
    for branch in ("char_tfidf","lexical_hgb"):
        params=next(params for b,params in candidate_grid(config) if b==branch)
        model,record=fit_candidate(rows,branch,params,parser,config["native_threads"],config["max_peak_bytes"])
        measurements.append(record)
        if model is None: raise DatasetError("resource_pilot_failed_"+record["status"])
    return {"schema":"url-pilot-v1","rows":len(rows),"group_count":len({r.domain_group for r in rows}),
            "case_ids":ids,"ids_sha256":hashlib.sha256(json.dumps(ids,separators=(",",":")).encode()).hexdigest(),
            "measurements":measurements,"native_threads":config["native_threads"],"max_peak_bytes":config["max_peak_bytes"]}


def select_model(splits,config,parser):
    import numpy as np
    from .metrics import choose_threshold,point_metrics
    from .contracts import Selection
    train=splits.partitions["train"]; validation=splits.partitions["validation"]
    labels=np.array([r.label for r in validation]); urls=[r.url for r in validation]
    records=[]; best=None; best_rank=None; branch_models={}
    for index,(branch,params) in enumerate(candidate_grid(config)):
        model,record=fit_candidate(train,branch,params,parser,config["native_threads"],config["max_peak_bytes"])
        record={**record,"configuration_index":index}
        if model is not None and record["status"]=="ok":
            scores=raw_scores(model,urls); threshold=choose_threshold(labels,scores,config["max_fpr"])
            metrics=point_metrics(labels,scores,threshold)
            record.update({"raw_threshold":threshold,"validation":metrics})
            rank=(metrics["recall"] or 0,metrics["precision"] or 0,-index)
            candidate=(model,threshold,params,record,rank)
            if branch not in branch_models or rank>branch_models[branch][-1]: branch_models[branch]=candidate
            if best_rank is None or rank>best_rank: best=(model,branch,threshold,params,index); best_rank=rank
        records.append(record)
        print(json.dumps({"training_progress":{"configuration":index+1,"branch":branch,"status":record["status"],
                                              "peak_bytes":record.get("peak_bytes"),"fit_seconds":record.get("fit_seconds")}}),flush=True)
    if best is None: raise DatasetError("all_candidates_failed")
    model,branch,threshold,params,index=best
    # Keep the best fitted candidate per branch for the frozen final comparison.
    # No retraining and no test/calibration inputs are read here.
    report={"configurations":records,"selected_configuration":index,"max_fpr":config["max_fpr"],
            "bootstrap_replicates":config["bootstrap_replicates"],"selection_partitions":["train","validation"],
            "rule_validation":point_metrics(labels,np.array(rule_predictions(validation),dtype=float),.5)}
    selection=Selection(model,branch,threshold,params,report)
    selection.branch_candidates=branch_models
    return selection

def train_run(splits,config,parser):
    import numpy as np
    from .calibration import fit_calibration
    from .contracts import RunBundle
    from .splits import manifest_hash
    selection=select_model(splits,config,parser)
    rows=splits.partitions["calibration"]
    calibration=fit_calibration(np.array([r.label for r in rows]),raw_scores(selection.model,[r.url for r in rows]),selection.raw_threshold)
    provenance={**splits.manifest["provenance"],"split_manifest_sha256":manifest_hash(splits.manifest),"seed":config["seed"],
                "training_config":config,"calibration_ids_sha256":hashlib.sha256(json.dumps([r.case_id for r in rows]).encode()).hexdigest()}
    return RunBundle(selection,calibration,provenance)
