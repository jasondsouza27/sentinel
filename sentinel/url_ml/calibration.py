"""Sigmoid score mapping trained solely on the calibration partition."""
import numpy as np
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from .contracts import Calibration,DatasetError
from .metrics import _arrays

EPSILON=1e-6

def logit(scores):
    clipped=np.clip(np.asarray(scores,dtype=float),EPSILON,1-EPSILON)
    return np.log(clipped/(1-clipped))

def fit_calibration(labels,scores,raw_threshold):
    y,s,w=_arrays(labels,scores)
    report={"rows":len(y),"class_counts":{str(c):int((y==c).sum()) for c in (0,1)},"epsilon":EPSILON,
            "min_rows":100,"min_per_class":20,"method":"sigmoid_on_clipped_score_logits"}
    if len(y)<100 or any(report["class_counts"][str(c)]<20 for c in (0,1)):
        report["reason"]="insufficient_calibration_support"
        return Calibration("unavailable",None,None,None,report)
    try:
        model=LogisticRegression(C=1e6,solver="lbfgs",max_iter=1000,random_state=42)
        model.fit(logit(s).reshape(-1,1),y)
        slope=float(model.coef_[0,0]); intercept=float(model.intercept_[0])
        if not np.isfinite(slope) or not np.isfinite(intercept) or slope<=0:
            report["reason"]="nonpositive_or_invalid_slope"
            return Calibration("unavailable",None,None,None,report)
    except (ValueError,FloatingPointError):
        report["reason"]="calibration_fit_failed"
        return Calibration("unavailable",None,None,None,report)
    threshold=float(expit(slope*logit([raw_threshold])[0]+intercept)) if raw_threshold is not None else None
    return Calibration("available",slope,intercept,threshold,report)

def apply_calibration(calibration,scores):
    if calibration.status!="available": return None
    if calibration.slope is None or calibration.intercept is None or calibration.slope<=0 or not np.isfinite([calibration.slope,calibration.intercept]).all():
        raise DatasetError("invalid_calibration")
    result=expit(calibration.slope*logit(scores)+calibration.intercept)
    if not np.isfinite(result).all(): raise DatasetError("invalid_calibration")
    return result
