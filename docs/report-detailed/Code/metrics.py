"""Frozen-threshold metrics and whole-domain percentile intervals."""
import numpy as np
from sklearn.metrics import average_precision_score
from .contracts import DatasetError

METRICS=("precision","recall","f1","macro_f1","pr_auc","fpr","coverage","brier","ece")

def _arrays(labels,scores,weights=None):
    y=np.asarray(labels); s=np.asarray(scores,dtype=float)
    if y.ndim!=1 or s.shape!=y.shape or not len(y) or not np.all(np.isin(y,[0,1])) or not np.all(np.isfinite(s)) or np.any((s<0)|(s>1)):
        raise DatasetError("metric_inputs_invalid")
    w=np.ones(len(y)) if weights is None else np.asarray(weights,dtype=float)
    if w.shape!=y.shape or not np.all(np.isfinite(w)) or np.any(w<0) or w.sum()==0: raise DatasetError("metric_weights_invalid")
    return y,s,w

def predictions(scores,threshold):
    return np.zeros(len(scores),dtype=bool) if threshold is None else np.asarray(scores)>=threshold

def _divide(a,b): return float(a/b) if b>0 else None

def point_metrics(labels,scores,threshold,probabilities=None,weights=None):
    y,s,w=_arrays(labels,scores,weights); predicted=predictions(s,threshold)
    tn=float(w[(y==0)&~predicted].sum()); fp=float(w[(y==0)&predicted].sum())
    fn=float(w[(y==1)&~predicted].sum()); tp=float(w[(y==1)&predicted].sum())
    positive=tp+fn; negative=tn+fp
    pos_f1=_divide(2*tp,2*tp+fp+fn) if positive>0 else None; neg_f1=_divide(2*tn,2*tn+fp+fn) if negative>0 else None
    # Average precision is the declared non-interpolated PR area summary.
    ap=float(average_precision_score(y,s,sample_weight=w)) if positive>0 and negative>0 else None
    bins=[]; brier=ece=None
    if probabilities is not None:
        _,p,_=_arrays(y,probabilities,w)
        brier=float(np.average((p-y)**2,weights=w)); ece=0.
        indices=np.minimum((p*10).astype(int),9)
        for i in range(10):
            mask=indices==i; count=float(w[mask].sum())
            probability=float(np.average(p[mask],weights=w[mask])) if count else None
            observed=float(np.average(y[mask],weights=w[mask])) if count else None
            bins.append({"lower":i/10,"upper":(i+1)/10,"count":count,"mean_probability":probability,"observed_fraction":observed})
            if count: ece+=count/w.sum()*abs(probability-observed)
    return {"confusion":{"tn":tn,"fp":fp,"fn":fn,"tp":tp},"precision":_divide(tp,tp+fp),
            "recall":_divide(tp,positive),"fpr":_divide(fp,negative),"f1":pos_f1,
            "macro_f1":float((pos_f1+neg_f1)/2) if positive>0 and negative>0 and pos_f1 is not None and neg_f1 is not None else None,
            "pr_auc":ap,"pr_auc_kind":"average_precision","coverage":1.,"brier":brier,"ece":ece,"reliability_bins":bins}

def choose_threshold(labels,scores,max_fpr=.05):
    y,s,w=_arrays(labels,scores)
    if set(y)!={0,1} or not 0<=max_fpr<=1: raise DatasetError("threshold_class_or_budget_invalid")
    order=np.argsort(-s,kind="stable"); sorted_s=s[order]; sorted_y=y[order]
    tp=np.cumsum(sorted_y==1); fp=np.cumsum(sorted_y==0)
    ends=np.flatnonzero(np.r_[sorted_s[:-1]!=sorted_s[1:],True])
    positives=int((y==1).sum()); negatives=int((y==0).sum())
    best=None; rank=(0.,0.)
    for end in ends:
        if fp[end]/negatives>max_fpr: continue
        current=(tp[end]/positives,tp[end]/(tp[end]+fp[end]))
        if current>rank: best=float(sorted_s[end]); rank=current
    return best

def bootstrap_weights(groups,replicates=1000,seed=42):
    groups=np.asarray(groups); unique,inverse=np.unique(groups,return_inverse=True)
    if not len(unique): raise DatasetError("bootstrap_groups_empty")
    rng=np.random.default_rng(seed)
    for _ in range(replicates):
        sampled=rng.integers(0,len(unique),size=len(unique))
        multiplicities=np.bincount(sampled,minlength=len(unique))
        yield multiplicities[inverse]

def grouped_metrics(labels,scores,threshold,groups,probabilities=None,replicates=1000,seed=42):
    y,s,w=_arrays(labels,scores); groups=np.asarray(groups)
    if groups.shape!=y.shape: raise DatasetError("group_shape_invalid")
    report=point_metrics(y,s,threshold,probabilities)
    support=all(len(set(groups[y==label]))>=2 for label in (0,1))
    values={key:[] for key in METRICS}
    if support:
        for weights in bootstrap_weights(groups,replicates,seed):
            m=point_metrics(y,s,threshold,probabilities,weights)
            for key in METRICS:
                if m[key] is not None: values[key].append(m[key])
    report["intervals"]={key:np.percentile(values[key],[2.5,97.5]).tolist() if len(values[key])>=max(2,replicates//2) else None for key in METRICS}
    report["bootstrap"]={"unit":"domain_group","seed":seed,"replicates":replicates,"status":"complete" if support else "insufficient_group_support",
                         "valid_replicates":{k:len(v) for k,v in values.items()}}
    scenarios=[]
    for prevalence in (.001,.01,.05,.1):
        recall,fpr=report["recall"],report["fpr"]
        expected=None if recall is None or fpr is None else _divide(recall*prevalence,recall*prevalence+fpr*(1-prevalence))
        scenarios.append({"assumed_prevalence":prevalence,"expected_precision":expected})
    report["prevalence_scenarios"]=scenarios
    return report

def evaluate_frozen(run,rows,seed=42):
    from .training import raw_scores
    from .calibration import apply_calibration
    scores=raw_scores(run.selection.model,[r.url for r in rows])
    probabilities=apply_calibration(run.calibration,scores)
    report=grouped_metrics([r.label for r in rows],scores,run.selection.raw_threshold,[r.domain_group for r in rows],probabilities,
                          run.selection.report.get("bootstrap_replicates",1000),seed)
    from collections import Counter
    categories=Counter()
    decisions=predictions(scores,run.selection.raw_threshold)
    for r,predicted in zip(rows,decisions):
        if int(predicted)==r.label: continue
        kind="false_positive" if predicted else "false_negative"
        categories[kind]+=1
        for flag,present in (("query_present","?" in r.url),("encoding_present","%" in r.url),("punycode_present","xn--" in r.url),("userinfo_present","@" in r.url)):
            if present: categories[kind+"_"+flag]+=1
    report["error_categories"]=dict(categories)
    report["rows"]=len(rows); report["groups"]=len({r.domain_group for r in rows})
    report["raw_threshold"]=run.selection.raw_threshold; report["calibration_status"]=run.calibration.status
    return report
