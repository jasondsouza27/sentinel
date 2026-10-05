"""Optional inference boundary; importable without any ML dependencies."""
import threading
from pathlib import Path
from .contracts import UrlAssessment,UnsupportedUrl

MISSING=("Live reputation lookup is not part of this model.","Site behaviour, redirects, DNS and account history were not checked.")
UNCERTAINTY=("This model learned historical URL annotations; live-site accuracy is unvalidated.","A not-flagged result does not establish safety.")

class UrlModelService:
    def __init__(self,artifact_path:Path):
        self._gate=threading.BoundedSemaphore(1); self._run=None; self._reason="artifact_unavailable"
        try:
            from .artifacts import load_artifact
            self._run=load_artifact(Path(artifact_path)); self._reason=None
        except Exception as error:
            self._reason=getattr(error,"reason","optional_model_unavailable")

    def health(self):
        return {"state":"ready" if self._run else "unavailable","model_version":self._run.provenance["artifact_version"] if self._run else None,"reason":self._reason}

    def _unavailable(self,reason="Model unavailable; verify independently or retry later."):
        version=self._run.provenance["artifact_version"] if self._run else None
        return UrlAssessment("unavailable",None,version,(),UNCERTAINTY,MISSING,reason)

    def assess(self,url):
        version=self._run.provenance["artifact_version"] if self._run else None
        if url is None or url=="":
            return UrlAssessment("not_assessed",None,version,(),UNCERTAINTY,MISSING+("No explicit URL was submitted to the URL model.",),"Submit one HTTP(S) URL to assess it.")
        if not self._run: return self._unavailable()
        if not self._gate.acquire(blocking=False): return self._unavailable("Model is busy; retry after the current assessment.")
        try:
            from .training import raw_scores
            from .calibration import apply_calibration
            from .features import lexical_features
            model=self._run.selection.model
            parser=next(step.parser for step in model.named_steps.values() if hasattr(step,"parser"))
            parsed=parser.normalize(url); scores=raw_scores(model,[parsed.model_url])
            threshold=self._run.selection.raw_threshold
            flagged=threshold is not None and float(scores[0])>=threshold
            calibrated=apply_calibration(self._run.calibration,scores)
            probability=float(calibrated[0]) if calibrated is not None else None
            facts=lexical_features(parsed); evidence=[]
            if "user_info" in parsed.flags: evidence.append("The URL contains user information before the destination host.")
            if "ip_host" in parsed.flags: evidence.append("The destination host is an IP address.")
            if "punycode" in parsed.flags: evidence.append("The host uses punycode; verify the intended spelling.")
            if "unknown_suffix" in parsed.flags: evidence.append("The host suffix is absent from the frozen suffix snapshot.")
            if facts["encoding_count"]: evidence.append("The URL contains percent-encoded characters.")
            if facts["url_length"]>180: evidence.append("The URL is longer than 180 characters.")
            if not evidence: evidence.append("No listed structural warning was observed; this does not establish safety.")
            uncertainty=UNCERTAINTY+(("The probability is calibrated on the source benchmark distribution.",) if probability is not None else ("Numerical probability is unavailable because calibration is invalid or unsupported.",))
            return UrlAssessment("complete","phishing_flag" if flagged else "not_flagged",version,tuple(evidence),uncertainty,MISSING,
                                 "Verify the sender and destination through an official channel before entering credentials or paying.",probability)
        except UnsupportedUrl as error:
            return UrlAssessment("not_assessed",None,version,(),UNCERTAINTY,MISSING+("Unsupported URL: "+error.reason,),"Submit a valid HTTP(S) URL no longer than 2,048 characters.")
        except Exception: return self._unavailable("Assessment failed; verify independently or retry later.")
        finally: self._gate.release()
