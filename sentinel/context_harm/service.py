"""Lightweight optional harm boundary. Initial bundles are research-only."""
import threading
from pathlib import Path

from .contracts import ConversationInput, HarmError


def unavailable(request: ConversationInput, reason: str, *, version=None) -> dict:
    coverage=dict(request.coverage)
    coverage['language']=request.language
    coverage['language_assumed']=request.language_assumed
    result={'schema_version':1,'task_id':'english_directed_abuse','state':'unavailable',
        'category':'not_assessed','branch':'context_cpu' if request.model_input.context else 'target_cpu',
        'target_id':request.target_id,'coverage':coverage,'evidence':[],
        'unavailable_checks':[reason.replace('_',' ')],
        'uncertainty':'A content label cannot establish intent or a pattern of harassment. Numerical probability is unavailable.',
        'action':'Review the target and preceding conversation before deciding whether to report it.',
        'model_version':version}
    if request.language!='en' or not request.model_input.target.strip():
        result.update(state='not_assessed',category='not_assessed')
        result['unavailable_checks']=['The learned task supports declared English target text only.'
            if request.language!='en' else 'No selected target was supplied for learned assessment.']
    return result


class HarmService:
    def __init__(self, artifact_path: Path|None, neural_python: Path|None=None):
        self._path=Path(artifact_path).resolve() if artifact_path else None
        self._python=Path(neural_python).resolve() if neural_python else None
        self._gate=threading.Lock()

    def health(self) -> dict:
        if self._path is None:
            return {'state':'unavailable','reason':'artifact_not_configured','model_version':None}
        try:
            from .artifacts import inspect_artifact
            metadata=inspect_artifact(self._path,research=True)
            version=metadata.get('model_version',metadata.get('artifact_version'))
            # A separate release specification/approval is required before this
            # schema can ever become a live warning. No editable flag bypass.
            return {'state':'unavailable','reason':'research_only_artifact','model_version':version}
        except Exception:
            return {'state':'unavailable','reason':'artifact_unavailable','model_version':None}

    def assess(self, request: ConversationInput) -> dict:
        if request.language!='en' or not request.model_input.target.strip():
            return unavailable(request,'unsupported_target')
        if not self._gate.acquire(blocking=False): return unavailable(request,'model_busy')
        try:
            health=self.health()
            result=unavailable(request,health['reason'],version=health.get('model_version'))
            # These are observed facts, kept separate from any prediction.
            if any(mark in request.model_input.target for mark in ('"','“','”')):
                result['evidence'].append('Quotation marks appear in the target; their meaning requires human review.')
            if request.model_input.context:
                result['evidence'].append('Only preceding conversation turns are supplied as context.')
            return result
        finally: self._gate.release()


def worker_infer(request: dict) -> dict:
    """Explicit offline research adapter; live service never admits this schema."""
    if request.get('research') is not True: raise HarmError('research_artifact_live_refused')
    from .artifacts import predict_research
    from .conversation import parse_submission
    return predict_research(Path(request['artifact']),parse_submission(request['input']))
