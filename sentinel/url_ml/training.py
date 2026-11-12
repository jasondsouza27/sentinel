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

def _own_peak_bytes(psutil):
    """This process's lifetime peak memory. psutil reports it only on Windows (peak_wset);
    on macOS/Linux use getrusage (ru_maxrss is bytes on macOS, kilobytes on Linux)."""
    info=psutil.Process().memory_info()
    peak=getattr(info,"peak_rss",None) or getattr(info,"peak_wset",None)
    if peak is None and os.name=="posix":
        import resource,sys
        maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak=maxrss if sys.platform=="darwin" else maxrss*1024
    return peak

def _fit_worker(connection,rows,branch,params,parser,native_threads,pipeline_factory=None):
    import psutil
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    from threadpoolctl import threadpool_limits
    started=time.perf_counter()
    try:
        with warnings.catch_warnings(record=True) as captured,threadpool_limits(limits=native_threads):
            warnings.simplefilter("always",ConvergenceWarning)
            if pipeline_factory is None: model=fit_pipeline(rows,branch,params,parser)
            else:
                model=pipeline_factory(branch,params,parser)
                model.fit([r.url for r in rows],[r.label for r in rows])
        peak=_own_peak_bytes(psutil)
        if peak is None: raise DatasetError("peak_memory_field_unavailable")
        convergence=any(issubclass(w.category,ConvergenceWarning) for w in captured)
        record={"status":"convergence_failure" if convergence else "ok","pid":os.getpid(),
                "peak_bytes":int(peak),"fit_seconds":time.perf_counter()-started,"native_threads":native_threads,
                "branch":branch,"params":params,"train_rows":len(rows)}
        connection.send((None if convergence else model,record))
    except Exception as error:
        try:
            peak=_own_peak_bytes(psutil)
        except psutil.Error: peak=None
        connection.send((None,{"status":"fit_failed","error":getattr(error,"reason",type(error).__name__),
                              "error_type":type(error).__name__,"error_message":str(error)[:2048],
                              "branch":branch,"params":params,"fit_seconds":time.perf_counter()-started,
                              "peak_bytes":peak,"native_threads":native_threads,"train_rows":len(rows),"pid":os.getpid()}))
    finally: connection.close()

def fit_candidate(rows,branch,params,parser,native_threads=4,max_peak_bytes=8*1024**3,*,pipeline_factory=None):
    import psutil
    ctx=multiprocessing.get_context("spawn"); receiving,sending=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_fit_worker,args=(sending,rows,branch,params,parser,native_threads,pipeline_factory))
    keys=("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS")
    previous={key:os.environ.get(key) for key in keys}
    try:
        for key in keys: os.environ[key]=str(native_threads)
        process.start()
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value
    sending.close(); record=None; result=None; observed_peak=0; tree_peak=0; conservative_peak=0
    known={}; individual_peaks={}; started=time.perf_counter()
    def sample():
        nonlocal observed_peak,tree_peak,conservative_peak
        try:
            worker=psutil.Process(process.pid)
            members=[worker,*worker.children(recursive=True)]
        except psutil.NoSuchProcess: members=[]
        for member in members:
            identity=(member.pid,member.create_time())
            known[identity]=member
        total=0
        for identity,member in list(known.items()):
            try:
                if member.create_time()!=identity[1]: continue
                info=member.memory_info(); rss=info.rss; total+=rss
                peak=getattr(info,"peak_rss",None) or getattr(info,"peak_wset",None) or rss
                individual_peaks[identity]=max(individual_peaks.get(identity,0),rss,peak)
                if member.pid==process.pid: observed_peak=max(observed_peak,rss)
            except psutil.NoSuchProcess: pass
        tree_peak=max(tree_peak,total)
        # This sum is conservative when individual lifetime peaks are not simultaneous.
        conservative_peak=max(conservative_peak,sum(individual_peaks.values()))
        return max(total,conservative_peak)
    def stop_tree(include_worker):
        try:
            worker=psutil.Process(process.pid)
            for member in worker.children(recursive=True):
                known[(member.pid,member.create_time())]=member
        except psutil.NoSuchProcess: pass
        targets=[]
        for identity,member in reversed(list(known.items())):
            # The worker itself is stopped through multiprocessing below: waiting on it with
            # psutil would reap it on POSIX and leave multiprocessing unable to close it.
            if member.pid==process.pid: continue
            try:
                if member.create_time()!=identity[1] or not member.is_running(): continue
                member.terminate(); targets.append(member)
            except psutil.NoSuchProcess: pass
        _,alive=psutil.wait_procs(targets,timeout=3)
        for member in alive:
            try: member.kill()
            except psutil.NoSuchProcess: pass
        _,alive=psutil.wait_procs(alive,timeout=3)
        if include_worker and process.is_alive():
            process.terminate(); process.join(3)
            if process.is_alive(): process.kill(); process.join(3)
        return not alive and not (include_worker and process.is_alive())
    try:
        while True:
            try: measured=sample()
            except psutil.Error:
                record={"status":"memory_measurement_failed","branch":branch,"params":params}; break
            if measured>max_peak_bytes:
                record={"status":"memory_budget_exceeded","branch":branch,"params":params}; break
            if receiving.poll(.05):
                try: result,record=receiving.recv()
                except EOFError: record={"status":"worker_exited","branch":branch,"params":params}
                try: measured=sample()
                except psutil.Error:
                    record["status"]="memory_measurement_failed"; result=None; break
                if measured>max_peak_bytes: record["status"]="memory_budget_exceeded"; result=None
                break
            if not process.is_alive():
                record={"status":"worker_exited","branch":branch,"params":params,"exit_code":process.exitcode}; break
        try:
            if not stop_tree(include_worker=result is None):
                record["status"]="worker_cleanup_failed"; result=None
        except psutil.Error: record["status"]="worker_cleanup_failed"; result=None
        process.join(timeout=5)
        if process.is_alive(): process.terminate(); process.join()
        worker_peak=record.get("peak_bytes")
        aggregate_peak=max(worker_peak or 0,conservative_peak)
        if aggregate_peak>max_peak_bytes: record["status"]="memory_budget_exceeded"; result=None
        record.update({"pid":process.pid,"monitored_process_count":len(known),
                       "worker_peak_bytes":worker_peak,"peak_bytes":aggregate_peak,
                       "observed_rss_peak_bytes":observed_peak,"observed_tree_rss_peak_bytes":tree_peak,
                       "conservative_tree_peak_bytes":conservative_peak,
                       "parent_wall_seconds":time.perf_counter()-started,"native_threads":native_threads,
                       "train_rows":len(rows),"max_peak_bytes":max_peak_bytes})
        return result,record
    finally:
        receiving.close()
        try: stop_tree(include_worker=True)
        except psutil.Error: pass
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

def _attempt_fit(rows,branch,params,parser,config):
    context={"branch":branch,"params":params,"train_rows":len(rows),
             "native_threads":config["native_threads"],"max_peak_bytes":config["max_peak_bytes"]}
    started=time.perf_counter()
    try:
        model,record=fit_candidate(rows,branch,params,parser,config["native_threads"],config["max_peak_bytes"])
        return model,{**context,**record}
    except Exception as error:
        # Spawn/serialization errors can occur before the worker sends a record.
        return None,{**context,"status":"fit_failed","error":getattr(error,"reason",type(error).__name__),
                     "error_type":type(error).__name__,"error_message":str(error)[:2048],
                     "fit_seconds":time.perf_counter()-started,"peak_bytes":None}


def _failure_context(splits,config):
    from .splits import manifest_hash
    return {"training_config":config,"split_provenance":splits.manifest.get("provenance",{}),
            "split_manifest_sha256":manifest_hash(splits.manifest)}


def resource_pilot(splits,config,parser):
    rows=pilot_rows(splits,config["pilot_max_rows"],config["seed"])
    ids=[r.case_id for r in rows]; measurements=[]
    report={"schema":"url-pilot-v1","rows":len(rows),"group_count":len({r.domain_group for r in rows}),
            "case_ids":ids,"ids_sha256":hashlib.sha256(json.dumps(ids,separators=(",",":")).encode()).hexdigest(),
            "measurements":measurements,"native_threads":config["native_threads"],"max_peak_bytes":config["max_peak_bytes"],
            **_failure_context(splits,config)}
    for branch in ("char_tfidf","lexical_hgb"):
        params=next(params for b,params in candidate_grid(config) if b==branch)
        model,record=_attempt_fit(rows,branch,params,parser,config)
        measurements.append(record)
        if model is None or record["status"]!="ok":
            reason="resource_pilot_failed_"+record["status"]
            report.update({"status":"failed","stage":"pilot","reason":reason})
            raise DatasetError(reason,diagnostics=report)
    return {**report,"status":"ok"}


def select_model(splits,config,parser):
    import numpy as np
    from .metrics import choose_threshold,point_metrics
    from .contracts import Selection
    train=splits.partitions["train"]; validation=splits.partitions["validation"]
    labels=np.array([r.label for r in validation]); urls=[r.url for r in validation]
    records=[]; best=None; best_rank=None; branch_models={}
    for index,(branch,params) in enumerate(candidate_grid(config)):
        model,record=_attempt_fit(train,branch,params,parser,config)
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
        progress={key:record.get(key) for key in ("branch","params","status","peak_bytes","fit_seconds",
                                                  "native_threads","observed_rss_peak_bytes","error","error_message")}
        print(json.dumps({"training_progress":{"configuration":index+1,**progress}}),flush=True)
    if best is None:
        raise DatasetError("all_candidates_failed",diagnostics={"schema":"url-training-failure-v1","stage":"selection",
                           "status":"failed","reason":"all_candidates_failed","configurations":records,
                           "train_rows":len(train),"validation_rows":len(validation),**_failure_context(splits,config)})
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
