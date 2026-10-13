"""Local compact encoder boundaries; optional ML imports occur only in workers."""
import math
from pathlib import Path
import sys

from .contracts import FrozenStudy, HarmCase, HarmError, ModelText, WorkerLimits
from .integrity import canonical_bytes, canonical_sha256, read_json, write_json
from .runtime import run_worker

MAX_SEQUENCE_TOKENS = 256
MAX_TARGET_TOKENS = 252
GPU_LIMIT_BYTES = 3435973836


def _load_tokenizer(directory: Path):
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,use_fast=True)
    except Exception:
        raise HarmError('neural_tokenizer_unavailable') from None


def _check_tokenizer(tokenizer):
    if (tokenizer.num_special_tokens_to_add(pair=True) != 3 or tokenizer.num_special_tokens_to_add(pair=False) != 2
            or tokenizer.pad_token_id is None or tokenizer.cls_token_id is None or tokenizer.sep_token_id is None):
        raise HarmError('neural_special_token_contract_changed')


def encode_model_text(value: ModelText, tokenizer, *, contextual: bool) -> dict:
    from .text import prepare_model_text
    _check_tokenizer(tokenizer)
    if not isinstance(value,ModelText):
        raise HarmError('neural_model_text_required')
    if (not value.target.strip() or len(value.target)>10000 or len(value.context)>4
            or len(value.target)+sum(len(turn) for turn in value.context)>20000):
        return {'supported':False,'reason':'character_coverage_unavailable'}
    value = prepare_model_text(value)
    target = tokenizer.encode(value.target,add_special_tokens=False)
    context = tokenizer.encode(' [CONTEXT_TURN] '.join(value.context),add_special_tokens=False) if value.context else []
    if not target or len(target)>MAX_TARGET_TOKENS or (contextual and not context):
        return {'supported':False,'reason':'target_token_limit' if len(target)>MAX_TARGET_TOKENS else 'context_unavailable',
                'target_tokens':len(target),'context_tokens':len(context),'target_tokens_used':0,'context_tokens_used':0,
                'context_turns_available':len(value.context),'context_turns_used':0,'context_turns_omitted':len(value.context)}
    used = context[-(MAX_SEQUENCE_TOKENS-3-len(target)):] if contextual else None
    inputs = tokenizer.build_inputs_with_special_tokens(target,used)
    expected = len(target)+2 if used is None else len(target)+len(used)+3
    expected_ids=[tokenizer.cls_token_id]+target+[tokenizer.sep_token_id]+([] if used is None else used+[tokenizer.sep_token_id])
    if inputs!=expected_ids or len(inputs)!=expected or len(inputs)>MAX_SEQUENCE_TOKENS:
        raise HarmError('neural_special_token_contract_changed')
    attention = [1]*len(inputs)+[0]*(MAX_SEQUENCE_TOKENS-len(inputs))
    inputs += [tokenizer.pad_token_id]*(MAX_SEQUENCE_TOKENS-len(inputs))
    turns_used=0
    if used is not None:
        offset=0; cutoff=len(context)-len(used)
        separator=tokenizer.encode(' [CONTEXT_TURN] ',add_special_tokens=False)
        assembled=[]
        for index,turn in enumerate(value.context):
            if index:
                assembled.extend(separator); offset+=len(separator)
            tokens=tokenizer.encode(turn,add_special_tokens=False)
            if tokens and offset+len(tokens)>cutoff:
                turns_used+=1
            assembled.extend(tokens); offset+=len(tokens)
        if assembled!=context:
            raise HarmError('neural_context_token_boundary_changed')
    return {'supported':True,'input_ids':inputs,'attention_mask':attention,'target_tokens':len(target),
            'target_tokens_used':len(target),'context_tokens':len(context),'context_tokens_used':len(used) if used is not None else 0,
            'context_truncated':contextual and len(used)<len(context),'target_truncated':False,
            'context_turns_available':len(value.context),'context_turns_used':turns_used,'context_turns_omitted':len(value.context)-turns_used}


def token_compatible_cases(rows: tuple[HarmCase,...], tokenizer_dir: Path) -> tuple[tuple[HarmCase,...],dict]:
    tokenizer = _load_tokenizer(tokenizer_dir)
    _check_tokenizer(tokenizer)
    coverage = {row.case_id:encode_model_text(row.model_input,tokenizer,contextual=True) for row in rows}
    if len(coverage)!=len(rows):
        raise HarmError('neural_duplicate_case_identity')
    compatible = tuple(row for row in rows if coverage[row.case_id]['supported'])
    # Public coverage contains counts, never content or token IDs.
    clean = {identity:{k:v for k,v in value.items() if k not in {'input_ids','attention_mask'}} for identity,value in coverage.items()}
    return compatible, {'total_cases':len(rows),'supported_cases':len(compatible),'case_coverage':clean,
                        'compatible_case_ids_sha256':canonical_sha256([row.case_id for row in compatible]),
                        'max_target_tokens':MAX_TARGET_TOKENS,'sequence_length':MAX_SEQUENCE_TOKENS,'pair_special_tokens':3}


def _unavailable(output: Path, reason: str, **extra) -> dict:
    record = {'schema_version':1,'status':'neural_unavailable','reason':reason,'may_fit_full_candidate':False,**extra}
    write_json(output,record)
    return record


def probe_neural_runtime(python: Path, output: Path) -> dict:
    python, output = Path(python), Path(output)
    if not python.is_file():
        return _unavailable(output,'neural_python_unavailable')
    result = run_worker([str(python),'-m','sentinel.context_harm.worker','--request-stdin'],WorkerLimits(60,8589934592,4),
                        input_payload=canonical_bytes({'operation':'neural_probe'}))
    if result.status!='ok':
        return _unavailable(output,result.reason or 'neural_runtime_unavailable',worker_runtime=result.measurements)
    value = result.output
    if value.get('status')!='ready' or not all(value.get('cuda_smoke',{}).get(stage) is True for stage in ('forward','backward','optimizer')):
        return _unavailable(output,value.get('reason','cuda_smoke_unavailable'),worker_runtime=result.measurements)
    if not _runtime_record_valid(value):
        return _unavailable(output,'neural_runtime_record_invalid',worker_runtime=result.measurements)
    record = {**value,'schema_version':1,'may_fit_full_candidate':False,'neural_python':str(python.resolve()),
              'worker_runtime':result.measurements}
    write_json(output,record)
    return record


def run_neural_pilot(study: FrozenStudy, python: Path, sources: dict, output: Path) -> dict:
    from .protocol import assert_fitting_allowed
    try:
        assert_fitting_allowed(study)
    except (HarmError,OSError):
        return _unavailable(output,'protected_cohort_unavailable')
    from .neural_sources import verify_sources
    try:
        verify_sources(sources)
    except (HarmError,OSError):
        return _unavailable(output,'neural_sources_unavailable_or_changed')
    probe = probe_neural_runtime(python,Path(output).with_name(Path(output).stem+'-runtime.json'))
    if probe.get('status')!='ready':
        return _unavailable(output,probe.get('reason','neural_runtime_unavailable'),probe=probe)
    result = run_worker([str(python),'-m','sentinel.context_harm.worker','--request-stdin'],WorkerLimits(600,8589934592,4),
                        input_payload=canonical_bytes({'operation':'neural_pilot','study_path':str(Path(study.path).resolve()),
                        'study_manifest_sha256':canonical_sha256(study.manifest),'sources':sources,'probe':probe}))
    if result.status!='ok':
        return _unavailable(output,result.reason or 'neural_pilot_unavailable',worker_runtime=result.measurements)
    value = result.output
    if (value.get('status')!='ready' or value.get('optimizer_steps')!=20 or value.get('pilot_rows',0)>32
            or value.get('pilot_rows',0)<2 or not isinstance(value.get('forecast_seconds'),(float,int))
            or not math.isfinite(value['forecast_seconds']) or value['forecast_seconds']>1800
            or any(type(value.get(field)) is not int or not 0<=value[field]<=GPU_LIMIT_BYTES
                   for field in ('peak_allocated_bytes','peak_reserved_bytes'))):
        return _unavailable(output,value.get('reason','neural_pilot_gates_failed'),worker_runtime=result.measurements)
    if not _cohort_report_valid(value.get('compatible_cohort',{})):
        return _unavailable(output,'neural_compatible_cohort_unavailable',worker_runtime=result.measurements)
    record = {**value,'schema_version':1,'may_fit_full_candidate':True,'neural_python':str(Path(python).resolve()),
              'report_path':str(Path(output).resolve()),
              'study_manifest_sha256':canonical_sha256(study.manifest),'source_manifest_sha256':sources['source_manifest_sha256'],
              'sources':sources,'probe':probe,'worker_runtime':result.measurements}
    write_json(output,record)
    return record

from dataclasses import asdict
import hashlib
import importlib.metadata
import os
import platform
import random
import shutil
import subprocess
import tempfile
import threading
import time

from .contracts import CandidateRef,PRODUCTION_CRITERIA,ScoreBatch
from .integrity import publish_stage,sha256
from .neural_sources import CATALOG_SHA256,MODEL_FILES,MODEL_ID,REVISION,load_catalog

NEURAL_KINDS = ('target_neural','context_neural')
NEURAL_IMPLEMENTATION_FILES = ('neural.py','neural_sources.py','text.py','worker.py','runtime.py','contracts.py','integrity.py')
TOKENIZER_FILES = ('tokenizer.json','tokenizer_config.json','vocab.txt')
CANDIDATE_MEMBERS = set(MODEL_FILES) | {'source-provenance.json'}
_NEURAL_FIT_LOCK = threading.Lock()


def _repository():
    return Path(__file__).resolve().parents[2]


def _lf_hash(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def implementation_hashes():
    directory=Path(__file__).resolve().parent
    return {name:_lf_hash(directory/name) for name in NEURAL_IMPLEMENTATION_FILES}


def expected_inventory():
    catalog=load_catalog(_repository()/'output/research/context-harm-neural-package-catalog.json')
    return {package['name']:package['version'] for package in catalog['packages']}


def runtime_identity_for_inventory(inventory, *, python_executable_sha256,base_executable_sha256,cuda_version,device_name,device_total_bytes,amp_supported):
    return {'catalog_sha256':CATALOG_SHA256,'neural_lock_sha256':_lf_hash(_repository()/'requirements-harm-neural-win-py311.lock.txt'),
            'inventory':inventory,'python_version':'3.11.17','platform':'Windows','architecture':'AMD64',
            'python_executable_sha256':python_executable_sha256,'base_executable_sha256':base_executable_sha256,
            'cuda_version':cuda_version,'device_name':device_name,'device_total_bytes':device_total_bytes,'amp_supported':amp_supported}


def _runtime_record_valid(record):
    binding=record.get('runtime_binding',{})
    return (isinstance(binding,dict) and binding.get('inventory')==expected_inventory()
            and binding.get('catalog_sha256')==CATALOG_SHA256 and binding.get('python_version')=='3.11.17'
            and binding.get('platform')=='Windows' and binding.get('architecture')=='AMD64' and binding.get('cuda_version')=='12.8'
            and binding.get('neural_lock_sha256')==_lf_hash(_repository()/'requirements-harm-neural-win-py311.lock.txt')
            and type(binding.get('device_total_bytes')) is int and binding['device_total_bytes']>=GPU_LIMIT_BYTES
            and type(binding.get('amp_supported')) is bool and isinstance(binding.get('device_name'),str)
            and record.get('runtime_sha256')==canonical_sha256(binding)
            and all(isinstance(binding.get(field),str) and len(binding[field])==64
                    for field in ('python_executable_sha256','base_executable_sha256'))
            and all(record.get('cuda_smoke',{}).get(stage) is True for stage in ('forward','backward','optimizer'))
            and all(type(record.get(field)) is int and 0<=record[field]<=GPU_LIMIT_BYTES
                    for field in ('peak_allocated_bytes','peak_reserved_bytes')))


def _runtime_inventory():
    expected=expected_inventory()
    installed={}
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata.get('Name','').lower().replace('_','-')
        installed[name]=distribution.version
    installer=installed.pop('pip',None)
    if installed!=expected or sys.version_info[:3]!=(3,11,17) or os.name!='nt' or platform.machine().upper() not in {'AMD64','X86_64'}:
        raise HarmError('neural_runtime_inventory_mismatch')
    return installed,installer


def _gpu_memory(torch):
    torch.cuda.synchronize()
    allocated,reserved=int(torch.cuda.max_memory_allocated()),int(torch.cuda.max_memory_reserved())
    if allocated>GPU_LIMIT_BYTES or reserved>GPU_LIMIT_BYTES:
        raise HarmError('neural_gpu_budget_exceeded')
    return {'peak_allocated_bytes':allocated,'peak_reserved_bytes':reserved}


def _cuda_smoke(torch):
    if not torch.cuda.is_available():
        raise HarmError('cuda_unavailable')
    torch.set_num_threads(4)
    torch.set_num_interop_threads(4)
    torch.cuda.reset_peak_memory_stats()
    stage='forward'
    try:
        model=torch.nn.Linear(4,2).to('cuda')
        optimizer=torch.optim.AdamW(model.parameters(),lr=2e-5,weight_decay=.01)
        inputs=torch.ones((2,4),device='cuda')
        labels=torch.tensor([0,1],device='cuda')
        loss=torch.nn.CrossEntropyLoss()(model(inputs),labels)
        if not bool(torch.isfinite(loss).item()):
            raise HarmError('cuda_nonfinite_smoke')
        stage='backward'; loss.backward()
        stage='optimizer'; optimizer.step()
        if any(not bool(torch.isfinite(parameter).all().item()) for parameter in model.parameters()):
            raise HarmError('cuda_nonfinite_smoke')
        return {'forward':True,'backward':True,'optimizer':True,'finite_loss':float(loss.detach().cpu()),**_gpu_memory(torch)}
    except HarmError:
        raise
    except Exception:
        raise HarmError('cuda_'+stage+'_failed') from None


def _worker_probe():
    try:
        inventory,installer=_runtime_inventory()
        check=subprocess.run([sys.executable,'-m','pip','check'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45)
        if check.returncode!=0:
            raise HarmError('neural_pip_check_failed')
        import torch
        smoke=_cuda_smoke(torch)
        identity=runtime_identity_for_inventory(inventory,python_executable_sha256=sha256(Path(sys.executable)),
                    base_executable_sha256=sha256(Path(sys._base_executable)),cuda_version=torch.version.cuda,
                    device_name=torch.cuda.get_device_name(0),device_total_bytes=int(torch.cuda.get_device_properties(0).total_memory),
                    amp_supported=torch.cuda.get_device_capability(0)[0]>=7)
        if identity['cuda_version']!='12.8' or identity['device_total_bytes']<GPU_LIMIT_BYTES:
            raise HarmError('cuda_runtime_or_capacity_unavailable')
        return {'status':'ready','may_fit_full_candidate':False,'runtime_binding':identity,'runtime_sha256':canonical_sha256(identity),
                'bootstrap_installer':{'name':'pip','version':installer},'pip_check':'passed','cuda_smoke':smoke,
                'peak_allocated_bytes':smoke['peak_allocated_bytes'],'peak_reserved_bytes':smoke['peak_reserved_bytes']}
    except Exception as error:
        reason=error.reason if isinstance(error,HarmError) else 'neural_runtime_import_unavailable'
        return {'status':'neural_unavailable','reason':reason,'may_fit_full_candidate':False}


def balanced_pilot_rows(rows):
    classes={label:sorted((row for row in rows if row.label==label),key=lambda row:row.case_id) for label in (0,1)}
    if any(len(values)<16 for values in classes.values()):
        raise HarmError('neural_pilot_class_support_unavailable')
    generator=random.Random(42)
    for values in classes.values():
        generator.shuffle(values)
    selected=classes[0][:16]+classes[1][:16]
    generator.shuffle(selected)
    return tuple(selected)


def forecast_candidate_seconds(load_seconds,optimizer_seconds,optimizer_steps,train_cases,validation_cases):
    values=(load_seconds,optimizer_seconds,optimizer_steps,train_cases,validation_cases)
    if any(not isinstance(value,(float,int)) or not math.isfinite(value) or value<0 for value in values) or optimizer_steps<=0:
        raise HarmError('neural_pilot_measurements_invalid')
    # Validation forward batches count as full optimizer steps; 50% margin.
    operations=3*(math.ceil(train_cases/8)+math.ceil(validation_cases/2))
    return float(load_seconds+1.5*(optimizer_seconds/optimizer_steps)*operations)


def compatible_cohort_manifest(partitions,components):
    report={'schema_version':1,'criteria':asdict(PRODUCTION_CRITERIA),'partitions':{},'unavailable_reasons':[]}
    for name,minimum in (('train',200),('validation',30),('calibration',30)):
        rows=partitions.get(name,())
        counts={str(label):sum(row.label==label for row in rows) for label in (0,1)}
        component_count=len({components[row.case_id] for row in rows})
        report['partitions'][name]={'case_count':len(rows),'class_counts':counts,'component_count':component_count,
               'case_ids_sha256':canonical_sha256([row.case_id for row in rows]),
               'features_labels_sha256':canonical_sha256([{'case_id':row.case_id,'label':row.label,
                    'target':row.model_input.target,'context':row.model_input.context} for row in rows])}
        if any(counts[str(label)]<minimum for label in (0,1)):
            report['unavailable_reasons'].append(name+'_class_support')
        if name!='train' and component_count<10:
            report['unavailable_reasons'].append(name+'_component_support')
    all_rows=[row for values in partitions.values() for row in values]
    component_sizes={}
    for row in all_rows:
        component=components[row.case_id]; component_sizes[component]=component_sizes.get(component,0)+1
    largest=max(component_sizes.values(),default=0)
    report['development_cases']=len(all_rows); report['largest_component_cases']=largest
    report['largest_component_fraction']=largest/len(all_rows) if all_rows else 0
    if report['largest_component_fraction']>.7:
        report['unavailable_reasons'].append('development_component_oversized')
    report['status']='neural_unavailable' if report['unavailable_reasons'] else 'ready'
    return report


def _compatible_development(study,sources):
    from .protocol import assert_fitting_allowed,load_development
    assert_fitting_allowed(study)
    original=load_development(study)
    tokenizer=_load_tokenizer(Path(sources['tokenizer_dir']))
    _check_tokenizer(tokenizer)
    partitions,coverage={},{}
    for name,rows in original.items():
        encoded={row.case_id:encode_model_text(row.model_input,tokenizer,contextual=True) for row in rows}
        partitions[name]=tuple(row for row in rows if encoded[row.case_id]['supported'])
        coverage[name]={'total_cases':len(rows),'supported_cases':len(partitions[name]),
                        'context_truncated_cases':sum(value.get('context_truncated',False) for value in encoded.values())}
    components=read_json(Path(study.path)/'components.json')['development']
    manifest=compatible_cohort_manifest(partitions,components)
    return partitions,manifest,coverage,tokenizer


def _seed(torch):
    import numpy as np
    random.seed(42); np.random.seed(42); torch.manual_seed(42); torch.cuda.manual_seed_all(42)
    os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.deterministic=True
    torch.use_deterministic_algorithms(True,warn_only=True)


def _load_training_model(sources,torch):
    from transformers import AutoModelForSequenceClassification
    _seed(torch)
    return AutoModelForSequenceClassification.from_pretrained(str(sources['model_dir']),num_labels=2,
             local_files_only=True,trust_remote_code=False,use_safetensors=True).to('cuda')


def _tensor_batch(rows,tokenizer,contextual,torch):
    encoded=[encode_model_text(row.model_input,tokenizer,contextual=contextual) for row in rows]
    if any(not value['supported'] for value in encoded):
        raise HarmError('neural_paired_coverage_changed')
    features={'input_ids':torch.tensor([value['input_ids'] for value in encoded],dtype=torch.long,device='cuda'),
              'attention_mask':torch.tensor([value['attention_mask'] for value in encoded],dtype=torch.long,device='cuda')}
    labels=torch.tensor([row.label for row in rows],dtype=torch.long,device='cuda')
    return features,labels


def _optimizer_group(model,optimizer,scaler,rows,tokenizer,contextual,torch,amp):
    optimizer.zero_grad(set_to_none=True)
    total_loss=0.0
    for start in range(0,len(rows),2):
        micro=rows[start:start+2]
        features,labels=_tensor_batch(micro,tokenizer,contextual,torch)
        with torch.autocast(device_type='cuda',dtype=torch.float16,enabled=amp):
            logits=model(**features).logits
            loss=torch.nn.CrossEntropyLoss()(logits,labels)
            weighted=loss*(len(micro)/len(rows))
        if not bool(torch.isfinite(loss).item()):
            raise HarmError('neural_nonfinite_training')
        total_loss+=float(loss.detach().float().cpu())*len(micro)
        scaler.scale(weighted).backward()
    scaler.unscale_(optimizer)
    try:
        torch.nn.utils.clip_grad_norm_(model.parameters(),1.0,error_if_nonfinite=True)
    except Exception:
        raise HarmError('neural_nonfinite_training') from None
    previous=float(scaler.get_scale())
    scaler.step(optimizer); scaler.update()
    if float(scaler.get_scale())<previous or any(not bool(torch.isfinite(parameter).all().item()) for parameter in model.parameters()):
        raise HarmError('neural_nonfinite_training')
    _gpu_memory(torch)
    return total_loss/len(rows)


def _predict_model(model,rows,tokenizer,contextual,torch,amp):
    model.eval(); values=[]
    with torch.inference_mode():
        for start in range(0,len(rows),2):
            features,_=_tensor_batch(rows[start:start+2],tokenizer,contextual,torch)
            with torch.autocast(device_type='cuda',dtype=torch.float16,enabled=amp):
                logits=model(**features).logits
            probabilities=torch.softmax(logits.float(),dim=-1)[:,1]
            if not bool(torch.isfinite(probabilities).all().item()):
                raise HarmError('neural_nonfinite_scores')
            values.extend(float(value) for value in probabilities.cpu().tolist())
    _gpu_memory(torch)
    return values


def _worker_pilot(request):
    from .protocol import assert_fitting_allowed
    path=Path(request['study_path']); study=FrozenStudy(path,read_json(path/'manifest.json'))
    if canonical_sha256(study.manifest)!=request.get('study_manifest_sha256'):
        raise HarmError('neural_study_manifest_changed')
    assert_fitting_allowed(study)
    sources=_verified_sources(request['sources'])
    partitions,cohort,coverage,tokenizer=_compatible_development(study,sources)
    if cohort['status']!='ready':
        return {'status':'neural_unavailable','reason':'neural_compatible_cohort_unavailable','may_fit_full_candidate':False,'compatible_cohort':cohort}
    probe=request['probe']
    if not _runtime_record_valid(probe):
        raise HarmError('neural_runtime_record_invalid')
    _runtime_inventory()
    import torch
    _seed(torch)
    torch.set_num_threads(4); torch.set_num_interop_threads(4); torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter(); model=_load_training_model(sources,torch); load_seconds=time.perf_counter()-started
    chosen=balanced_pilot_rows(partitions['train'])
    optimizer=torch.optim.AdamW(model.parameters(),lr=2e-5,weight_decay=.01)
    amp=probe['runtime_binding']['amp_supported']; scaler=torch.amp.GradScaler('cuda',enabled=amp)
    optimizer_started=time.perf_counter(); losses=[]
    model.train()
    for step in range(20):
        offset=(step*8)%len(chosen)
        group=(chosen+chosen)[offset:offset+8]
        losses.append(_optimizer_group(model,optimizer,scaler,group,tokenizer,True,torch,amp))
    optimizer_seconds=time.perf_counter()-optimizer_started
    memory=_gpu_memory(torch)
    forecast=forecast_candidate_seconds(load_seconds,optimizer_seconds,20,len(partitions['train']),len(partitions['validation']))
    assert_fitting_allowed(study)
    if forecast>1800:
        return {'status':'neural_unavailable','reason':'neural_forecast_exceeds_deadline','may_fit_full_candidate':False,
                'forecast_seconds':forecast,**memory}
    return {'status':'ready','pilot_rows':len(chosen),'pilot_class_counts':{'0':16,'1':16},'optimizer_steps':20,
            'pilot_case_ids_sha256':canonical_sha256([row.case_id for row in chosen]),'compatible_cohort':cohort,'coverage':coverage,
            'model_load_seconds':load_seconds,'optimizer_seconds':optimizer_seconds,'mean_loss':sum(losses)/len(losses),
            'forecast_seconds':forecast,'amp_enabled':amp,**memory}


def neural_candidate_grid():
    return tuple({'kind':kind,'learning_rate':rate,'config_id':kind+'-lr'+format(rate,'.0e').replace('e-0','e-')}
                 for kind in NEURAL_KINDS for rate in (2e-5,5e-5))


def _validation_report(rows,scores):
    labels=[row.label for row in rows]
    if len(scores)!=len(labels) or set(labels)!={0,1} or any(not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=1 for value in scores):
        raise HarmError('neural_validation_scores_invalid')
    positives,negatives=labels.count(1),labels.count(0)
    best={'recall':0.0,'precision':0.0,'fpr':0.0,'raw_threshold':None}
    rank=(0.0,0.0,0.0)
    for threshold in sorted(set(scores),reverse=True):
        tp=sum(label==1 and score>=threshold for label,score in zip(labels,scores))
        fp=sum(label==0 and score>=threshold for label,score in zip(labels,scores))
        if fp/negatives>.05:
            continue
        new=(tp/positives,tp/(tp+fp) if tp+fp else 0,-fp/negatives)
        if new>rank:
            rank=new; best={'recall':new[0],'precision':new[1],'fpr':fp/negatives,'raw_threshold':float(threshold)}
    return best


def fit_epoch_loop(training,validation,fit_epoch,validate,retain_checkpoint,config_id):
    generator=random.Random(42); reports=[]; best_rank=None; chosen=None
    for epoch in range(1,4):
        ordered=list(training); generator.shuffle(ordered)
        fit=fit_epoch(tuple(ordered))
        loss=fit.get('mean_loss')
        if not isinstance(loss,(float,int)) or not math.isfinite(loss):
            raise HarmError('neural_nonfinite_training')
        scores=validate(tuple(validation))
        report=_validation_report(validation,scores)
        rank=(report['recall'],report['precision'],-report['fpr'])
        reports.append({'epoch':epoch,'fit':fit,'validation':report})
        if best_rank is None or rank>best_rank:
            best_rank=rank; chosen={'selected_epoch':epoch,'validation_report':report}; retain_checkpoint(epoch)
    return {**chosen,'selection_partition':'validation','config_id':config_id,'epoch_reports':reports}


def candidate_fit_record(request,directory,report):
    sources,pilot=request['sources'],request['pilot']
    base=sources['manifest']['model']['members']
    tokenizer={name:base[name] for name in TOKENIZER_FILES}
    provenance={'base_model_id':MODEL_ID,'revision':REVISION,'base_members':base,'tokenizer_members':tokenizer,
                'source_manifest_sha256':sources['source_manifest_sha256'],'catalog_sha256':CATALOG_SHA256,
                'model_metadata':sources['manifest']['model']['metadata']}
    write_json(Path(directory)/'source-provenance.json',provenance,exclusive=True)
    code=implementation_hashes()
    members={name:sha256(Path(directory)/name) for name in CANDIDATE_MEMBERS}
    return {'schema_version':1,'task_id':'english_directed_abuse','status':'ok','kind':request['kind'],'config_id':request['config_id'],
            'learning_rate':request['learning_rate'],'study_manifest_sha256':request['study_manifest_sha256'],
            'pilot_sha256':canonical_sha256(pilot),'source_manifest_sha256':sources['source_manifest_sha256'],
            'compatible_cohort':pilot['compatible_cohort'],'compatible_cohort_sha256':canonical_sha256(pilot['compatible_cohort']),
            'tokenizer_base_hashes':provenance,'runtime_probe':pilot['probe'],'runtime_sha256':pilot['probe']['runtime_sha256'],
            'neural_python':request['neural_python'],'synthetic':request['synthetic'],'implementation':code,
            'implementation_sha256':canonical_sha256(code),'neural_lock_sha256':_lf_hash(_repository()/'requirements-harm-neural-win-py311.lock.txt'),
            'catalog_sha256':CATALOG_SHA256,'members':members,'settings':request['settings']['neural'],
            'determinism_limitations':['CUDA kernels may be nondeterministic','generic pretraining may have historical overlap'],**report}


def checked_candidate(candidate):
    record=read_json(Path(candidate.directory)/'fit-record.json',max_bytes=4*1024**2)
    if record!=candidate.fit_record:
        raise HarmError('neural_fit_record_changed')
    entry=next((entry for entry in neural_candidate_grid() if entry['kind']==candidate.kind and entry['config_id']==candidate.config_id),None)
    if (entry is None or record.get('schema_version')!=1 or record.get('task_id')!='english_directed_abuse' or record.get('status')!='ok'
            or record.get('kind')!=candidate.kind or record.get('config_id')!=candidate.config_id or record.get('learning_rate')!=entry['learning_rate']
            or record.get('selection_partition')!='validation' or record.get('selected_epoch') not in (1,2,3)):
        raise HarmError('neural_fit_record_invalid')
    code=implementation_hashes()
    if record.get('implementation')!=code or record.get('implementation_sha256')!=canonical_sha256(code):
        raise HarmError('neural_implementation_changed')
    if record.get('catalog_sha256')!=CATALOG_SHA256 or record.get('neural_lock_sha256')!=_lf_hash(_repository()/'requirements-harm-neural-win-py311.lock.txt'):
        raise HarmError('neural_lock_changed')
    probe=record.get('runtime_probe',{})
    if not _runtime_record_valid(probe) or record.get('runtime_sha256')!=probe.get('runtime_sha256'):
        raise HarmError('neural_runtime_binding_changed')
    cohort=record.get('compatible_cohort',{})
    if not _cohort_report_valid(cohort) or record.get('compatible_cohort_sha256')!=canonical_sha256(cohort):
        raise HarmError('neural_compatible_cohort_changed')
    for field in ('study_manifest_sha256','source_manifest_sha256','pilot_sha256'):
        if not isinstance(record.get(field),str) or len(record[field])!=64:
            raise HarmError('neural_fit_record_invalid')
    if any(type(record.get(field)) is not int or not 0<=record[field]<=GPU_LIMIT_BYTES for field in ('peak_allocated_bytes','peak_reserved_bytes')):
        raise HarmError('neural_gpu_budget_exceeded')
    measured=record.get('fit_runtime',{})
    if (measured.get('ownership')!='windows_job_kill_on_close' or measured.get('cleanup_complete') is not True
            or measured.get('monitoring_complete') is not True or measured.get('native_threads')!=4
            or measured.get('rss_limit_bytes')!=8589934592 or measured.get('deadline_seconds')!=1800
            or type(measured.get('rss_peak_bytes')) is not int or not 0<measured['rss_peak_bytes']<=8589934592):
        raise HarmError('neural_fit_runtime_invalid')
    if set(record.get('members',{}))!=CANDIDATE_MEMBERS:
        raise HarmError('neural_model_member_invalid')
    for name,digest in record['members'].items():
        path=Path(candidate.directory)/name
        if not path.is_file() or path.stat().st_size>512*1024**2 or sha256(path)!=digest:
            raise HarmError('neural_model_member_changed')
    provenance=read_json(Path(candidate.directory)/'source-provenance.json')
    if (provenance!=record.get('tokenizer_base_hashes') or provenance.get('base_model_id')!=MODEL_ID or provenance.get('revision')!=REVISION
            or set(provenance.get('base_members',{}))!=set(MODEL_FILES) or set(provenance.get('tokenizer_members',{}))!=set(TOKENIZER_FILES)
            or provenance.get('source_manifest_sha256')!=record['source_manifest_sha256']
            or any(provenance['tokenizer_members'][name]!=record['members'][name] for name in TOKENIZER_FILES)):
        raise HarmError('neural_source_binding_changed')
    return record


def _pilot_checked(study,pilot):
    path=pilot.get('report_path')
    if not isinstance(path,str) or read_json(Path(path),max_bytes=4*1024**2)!=pilot:
        raise HarmError('neural_pilot_changed')
    if (pilot.get('status')!='ready' or pilot.get('may_fit_full_candidate') is not True
            or pilot.get('study_manifest_sha256')!=canonical_sha256(study.manifest)
            or not _cohort_report_valid(pilot.get('compatible_cohort',{})) or not _runtime_record_valid(pilot.get('probe',{}))
            or pilot.get('source_manifest_sha256')!=pilot.get('sources',{}).get('source_manifest_sha256')):
        raise HarmError('neural_pilot_changed')
    _verified_sources(pilot['sources'])
    return pilot


def _neural_settings(settings):
    from .source import default_settings
    if not isinstance(settings,dict) or settings.get('neural')!=default_settings()['neural']:
        raise HarmError('neural_settings_not_production')


def fit_neural_candidates(study,pilot,python,output,settings):
    output=Path(output).resolve(); failure=output.with_name(output.name+'.neural-unavailable.json')
    if pilot.get('status')!='ready' or pilot.get('may_fit_full_candidate') is not True:
        _unavailable(failure,pilot.get('reason','neural_pilot_unavailable'))
        return ()
    stage=None; acquired=False; measurements=[]
    try:
        _pilot_checked(study,pilot)
        _neural_settings(settings)
        from .protocol import assert_fitting_allowed,verify_study
        assert_fitting_allowed(study); binding=verify_study(study)
        if any(part.casefold()=='onedrive' for part in output.parts):
            raise HarmError('neural_private_path_in_onedrive')
        acquired=_NEURAL_FIT_LOCK.acquire(blocking=False)
        if not acquired:
            raise HarmError('neural_fitting_busy')
        if output.exists():
            raise HarmError('neural_output_already_exists')
        output.parent.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='.neural-stage-',dir=output.parent))
        for entry in neural_candidate_grid():
            assert_fitting_allowed(study)
            request={**entry,'operation':'neural_fit','study_path':str(Path(study.path).resolve()),
                    'study_manifest_sha256':canonical_sha256(study.manifest),'settings':settings,'pilot':pilot,'sources':pilot['sources'],
                    'neural_python':str(Path(python).resolve()),'synthetic':binding.get('synthetic',False),'output_directory':str(stage/entry['config_id'])}
            request_path=stage/(entry['config_id']+'-request.json'); write_json(request_path,request,exclusive=True)
            try:
                result=run_worker([str(python),'-m','sentinel.context_harm.worker','--request',str(request_path)],WorkerLimits(1800,8589934592,4))
            finally:
                request_path.unlink(missing_ok=True)
            measurements.append({'config_id':entry['config_id'],'status':result.status,'reason':result.reason,'measurements':result.measurements})
            if result.status!='ok':
                raise HarmError(result.reason or 'neural_fit_unavailable')
            record=result.output.get('fit_record')
            if not isinstance(record,dict) or record.get('study_manifest_sha256')!=canonical_sha256(study.manifest) or record.get('compatible_cohort_sha256')!=canonical_sha256(pilot['compatible_cohort']):
                raise HarmError('neural_worker_fit_binding_invalid')
            record={**record,'fit_runtime':result.measurements}
            directory=stage/entry['config_id']; write_json(directory/'fit-record.json',record,exclusive=True)
            checked_candidate(CandidateRef(entry['kind'],entry['config_id'],directory,record))
        assert_fitting_allowed(study)
        publish_stage(stage,output,{path.relative_to(stage).as_posix():sha256(path) for path in stage.rglob('*') if path.is_file()})
        return tuple(CandidateRef(entry['kind'],entry['config_id'],output/entry['config_id'],read_json(output/entry['config_id']/'fit-record.json',max_bytes=4*1024**2)) for entry in neural_candidate_grid())
    except (HarmError,OSError,KeyError,ValueError) as error:
        reason=error.reason if isinstance(error,HarmError) else 'neural_fit_unavailable'
        _unavailable(failure,reason,candidates=measurements)
        return ()
    finally:
        if stage is not None and stage.exists() and stage.resolve().parent==output.parent and stage.name.startswith('.neural-stage-'):
            shutil.rmtree(stage)
        if acquired:
            _NEURAL_FIT_LOCK.release()


def _worker_fit(request):
    from .protocol import assert_fitting_allowed
    path=Path(request['study_path']); study=FrozenStudy(path,read_json(path/'manifest.json'))
    assert_fitting_allowed(study)
    _pilot_checked(study,request['pilot']); _neural_settings(request['settings'])
    sources=_verified_sources(request['sources'])
    partitions,cohort,coverage,tokenizer=_compatible_development(study,sources)
    if cohort!=request['pilot']['compatible_cohort']:
        raise HarmError('neural_compatible_cohort_changed')
    entry=next((entry for entry in neural_candidate_grid() if entry['kind']==request['kind'] and entry['config_id']==request['config_id'] and entry['learning_rate']==request['learning_rate']),None)
    if entry is None:
        raise HarmError('neural_candidate_settings_invalid')
    _runtime_inventory()
    import torch
    torch.set_num_threads(4); torch.set_num_interop_threads(4); torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter(); model=_load_training_model(sources,torch)
    optimizer=torch.optim.AdamW(model.parameters(),lr=entry['learning_rate'],weight_decay=.01)
    amp=request['pilot']['probe']['runtime_binding']['amp_supported']; scaler=torch.amp.GradScaler('cuda',enabled=amp)
    contextual=entry['kind']=='context_neural'
    directory=Path(request['output_directory']); directory.mkdir(parents=True,exist_ok=False)
    def fit_epoch(rows):
        model.train(); total,steps=0.0,0
        for start in range(0,len(rows),8):
            group=rows[start:start+8]
            total+=_optimizer_group(model,optimizer,scaler,group,tokenizer,contextual,torch,amp)*len(group); steps+=1
        return {'mean_loss':total/len(rows),'optimizer_steps':steps}
    def validate(rows):
        return _predict_model(model,rows,tokenizer,contextual,torch,amp)
    def retain(epoch):
        model.save_pretrained(str(directory),safe_serialization=True,max_shard_size='1GB')
    report=fit_epoch_loop(partitions['train'],partitions['validation'],fit_epoch,validate,retain,entry['config_id'])
    for name in MODEL_FILES:
        if name not in {'model.safetensors','config.json'}:
            shutil.copyfile(Path(sources['model_dir'])/name,directory/name)
    report.update(_gpu_memory(torch)); report.update(fit_seconds=time.perf_counter()-started,coverage=coverage)
    assert_fitting_allowed(study)
    return {'fit_record':candidate_fit_record(request,directory,report)}


def score_neural(candidate,rows,runtime=None):
    record=checked_candidate(candidate)
    from .cpu import _feature_row,_score_limits,SCORE_BATCH_SIZE
    options={} if runtime is None else dict(runtime)
    options.setdefault('python',record['neural_python'])
    limits,python=_score_limits(options)
    features=tuple(_feature_row(row) for row in rows); ids=tuple(value['case_id'] for value in features)
    if len(set(ids))!=len(ids):
        raise HarmError('neural_duplicate_case_identity')
    values,covered,measurements=[],[],[]; started=time.perf_counter()
    aggregate={field:0 for field in TOKEN_COVERAGE_FIELDS}
    gpu_peaks={'peak_allocated_bytes':0,'peak_reserved_bytes':0}
    for start in range(0,len(features),SCORE_BATCH_SIZE):
        chunk=features[start:start+SCORE_BATCH_SIZE]
        payload=canonical_bytes({'operation':'neural_score','candidate_directory':str(Path(candidate.directory).resolve()),
                    'kind':candidate.kind,'config_id':candidate.config_id,'fit_record_sha256':canonical_sha256(record),'rows':chunk})
        result=run_worker([str(python),'-m','sentinel.context_harm.worker','--request-stdin'],limits,input_payload=payload)
        measurements.append(result.measurements)
        if result.status!='ok':
            return ScoreBatch(ids,(None,)*len(ids),(False,)*len(ids),{'status':'unavailable','reason':result.reason,'records':measurements})
        output=result.output
        if (output.get('case_ids')!=[value['case_id'] for value in chunk] or not isinstance(output.get('scores'),list)
                or not isinstance(output.get('coverage'),list) or len(output['scores'])!=len(chunk) or len(output['coverage'])!=len(chunk)
                or any(type(flag) is not bool for flag in output['coverage'])
                or any((type(score) not in (float,int) or not math.isfinite(score) or not 0<=score<=1) if flag else score is not None
                       for score,flag in zip(output['scores'],output['coverage']))):
            raise HarmError('neural_worker_scores_invalid')
        for field in gpu_peaks:
            value=output.get(field)
            if type(value) is not int or not 0<=value<=GPU_LIMIT_BYTES:
                raise HarmError('neural_gpu_budget_exceeded')
            gpu_peaks[field]=max(gpu_peaks[field],value)
        token_report=output.get('token_coverage')
        if (not isinstance(token_report,dict) or set(token_report)!=set(TOKEN_COVERAGE_FIELDS)
                or any(type(value) is not int or value<0 for value in token_report.values())
                or token_report['total_cases']!=len(chunk) or token_report['supported_cases']!=sum(output['coverage'])):
            raise HarmError('neural_worker_token_coverage_invalid')
        for field,value in token_report.items():
            aggregate[field]+=value
        values.extend(output['scores']); covered.extend(output['coverage'])
    return ScoreBatch(ids,tuple(values),tuple(covered),{'status':'ok','records':measurements,'wall_seconds':time.perf_counter()-started,
                         'rss_peak_bytes':max((value.get('rss_peak_bytes',0) for value in measurements),default=0),'token_coverage':aggregate,**gpu_peaks})


def _worker_score(request):
    from .cpu import _request_rows
    directory=Path(request['candidate_directory']); record=read_json(directory/'fit-record.json',max_bytes=4*1024**2)
    if canonical_sha256(record)!=request.get('fit_record_sha256'):
        raise HarmError('neural_fit_record_changed')
    candidate=CandidateRef(request['kind'],request['config_id'],directory,record); checked_candidate(candidate)
    _runtime_inventory()
    rows=_request_rows(request['rows']); tokenizer=_load_tokenizer(directory)
    contextual=candidate.kind=='context_neural'
    encodings=[encode_model_text(value,tokenizer,contextual=contextual) for _,value in rows]
    coverage=[value['supported'] for value in encodings]; values=[None]*len(rows)
    memory={'peak_allocated_bytes':0,'peak_reserved_bytes':0}
    if any(coverage):
        import torch
        from transformers import AutoModelForSequenceClassification
        torch.set_num_threads(4); torch.set_num_interop_threads(4); torch.cuda.reset_peak_memory_stats()
        if not torch.cuda.is_available():
            raise HarmError('cuda_unavailable')
        model=AutoModelForSequenceClassification.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,use_safetensors=True).to('cuda')
        if model.config.num_labels!=2:
            raise HarmError('neural_model_head_invalid')
        selected=tuple(HarmCase(identity,value,(),'inference',0,{}) for (identity,value),flag in zip(rows,coverage) if flag)
        scores=iter(_predict_model(model,selected,tokenizer,contextual,torch,record['runtime_probe']['runtime_binding']['amp_supported']))
        for index,flag in enumerate(coverage):
            if flag: values[index]=next(scores)
        memory=_gpu_memory(torch)
    return {'case_ids':[identity for identity,_ in rows],'scores':values,'coverage':coverage,'token_coverage':aggregate_token_coverage(encodings),**memory}


def worker_operation(request):
    operation=request.get('operation')
    if operation=='neural_probe':
        return _worker_probe()
    if operation=='neural_pilot':
        return _worker_pilot(request)
    if operation=='neural_fit':
        return _worker_fit(request)
    if operation=='neural_score':
        return _worker_score(request)
    raise HarmError('neural_worker_operation_invalid')


def _verified_sources(sources):
    from .neural_sources import verify_sources
    return verify_sources(sources)


TOKEN_COVERAGE_FIELDS=('total_cases','supported_cases','measured_token_cases','target_tokens_available','target_tokens_used',
        'context_tokens_available','context_tokens_used','context_truncated_cases','target_limit_abstentions',
        'context_turns_available','context_turns_used','context_turns_omitted')


def aggregate_token_coverage(encodings):
    report={field:0 for field in TOKEN_COVERAGE_FIELDS}
    report['total_cases']=len(encodings)
    for value in encodings:
        report['supported_cases']+=int(value['supported'])
        report['measured_token_cases']+=int('target_tokens' in value)
        report['target_tokens_available']+=value.get('target_tokens',0)
        report['target_tokens_used']+=value.get('target_tokens_used',0)
        report['context_tokens_available']+=value.get('context_tokens',0)
        report['context_tokens_used']+=value.get('context_tokens_used',0)
        report['context_truncated_cases']+=int(value.get('context_truncated',False))
        report['target_limit_abstentions']+=int(value.get('reason')=='target_token_limit')
        for field in ('context_turns_available','context_turns_used','context_turns_omitted'):
            report[field]+=value.get(field,0)
    return report


def _cohort_report_valid(report):
    if (not isinstance(report,dict) or report.get('status')!='ready' or report.get('unavailable_reasons')!=[]
            or report.get('criteria')!=asdict(PRODUCTION_CRITERIA) or set(report.get('partitions',{}))!={'train','validation','calibration'}):
        return False
    total=0
    for name,minimum in (('train',200),('validation',30),('calibration',30)):
        value=report['partitions'][name]; counts=value.get('class_counts',{})
        if (set(counts)!={'0','1'} or any(type(count) is not int or count<minimum for count in counts.values())
                or type(value.get('case_count')) is not int or value['case_count']!=sum(counts.values())
                or type(value.get('component_count')) is not int or not 1<=value['component_count']<=value['case_count']
                or (name!='train' and value['component_count']<10)
                or any(not isinstance(value.get(field),str) or len(value[field])!=64 for field in ('case_ids_sha256','features_labels_sha256'))):
            return False
        total+=value['case_count']
    largest=report.get('largest_component_cases'); fraction=report.get('largest_component_fraction')
    return (report.get('development_cases')==total and type(largest) is int and 0<largest<=total
            and isinstance(fraction,(float,int)) and math.isfinite(fraction) and fraction==largest/total and fraction<=.7)
