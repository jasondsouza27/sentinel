"""Invented sources and controlled workers; never evidence of CUDA compatibility."""
from dataclasses import asdict
from pathlib import Path
import sys

from sentinel.context_harm.contracts import CadUtterance,CaseCohort,HarmCase,ModelText,PRODUCTION_CRITERIA,SourceRelease,WorkerRecord
from sentinel.context_harm.integrity import canonical_sha256,sha256
from sentinel.context_harm.protocol import _freeze_cohort,load_development,read_json
from sentinel.context_harm.source import default_settings
from test_context_harm_neural_sources import model_fixture


def ready_study(root):
    rows,records=[],[]
    for index in range(300):
        for label in (0,1):
            identity=f'd{index}-{label}'; thread=f'thread{index}'
            target=f'Fixture label{label} item{index}'
            rows.append(HarmCase(identity,ModelText(target,(f'c{index}',)),(f'context{index}',),thread,label,{'source_split':'train'}))
            records.append(CadUtterance(identity,thread,None,None,None,('0',),target,'train',('PersonDirectedAbuse',) if label else ('Neutral',),(),True,True,{}))
    for index in range(100):
        for label in (0,1):
            identity=f'test{index}-{label}'; target=f'Held test example {index} class{label}'
            rows.append(HarmCase(identity,ModelText(target,(f'Test context {index}',)),(),identity,label,{'source_split':'test'}))
            records.append(CadUtterance(identity,identity,None,None,None,('0',),target,'test',('PersonDirectedAbuse',) if label else ('Neutral',),(),True,True,{}))
    cohort=CaseCohort(tuple(rows),(),SourceRelease(tuple(records),{'synthetic_fixture':True}),{})
    challenge={'schema_version':1,'case_count':0,'status':'pending','cad_case_ids':[],'duplicate_keys':[],'case_ids':[]}
    return _freeze_cohort(root/'study',cohort,default_settings(),challenge,criteria=PRODUCTION_CRITERIA,synthetic=True)


def fixture_sources(root):
    from sentinel.context_harm.neural_sources import CATALOG_SHA256,MODEL_ID,REVISION,model_metadata
    metadata,contents=model_fixture()
    directory=root/'invented-source'
    directory.mkdir()
    for name,content in contents.items():
        (directory/name).write_bytes(content)
    manifest={'schema_version':1,'fixture_provenance':'invented software fixtures; no source acquisition or CUDA run',
              'model':{'metadata':model_metadata(metadata),'members':{name:sha256(directory/name) for name in contents}},
              'wheels':{'members':{}}}
    return {'status':'ready','synthetic':True,'catalog_sha256':CATALOG_SHA256,'base_model_id':MODEL_ID,'revision':REVISION,
            'model_dir':str(directory),'tokenizer_dir':str(directory),'manifest':manifest,'source_manifest_sha256':canonical_sha256(manifest)}


def measured(seconds=1):
    return {'ownership':'windows_job_kill_on_close','cleanup_complete':True,'monitoring_complete':True,'native_threads':4,
            'rss_limit_bytes':8589934592,'rss_peak_bytes':200000000,'deadline_seconds':1800,'poll_seconds':.1,'pid':123456,
            'wall_seconds':seconds,'fixture_provenance':'controlled worker outcome; no native CUDA fit'}


class ControlledWorkers:
    def __init__(self,module,study,sources):
        self.module,self.study,self.sources=module,study,sources
        self.requests=[]

    def __call__(self,command,limits,*,input_payload=None,cancel=None):
        import json
        request=json.loads(input_payload) if input_payload is not None else read_json(Path(command[-1]))
        self.requests.append(request)
        module=self.module
        if request['operation']=='neural_probe':
            identity=module.runtime_identity_for_inventory(module.expected_inventory(),python_executable_sha256=sha256(Path(sys.executable)),
                         base_executable_sha256=sha256(Path(sys._base_executable)),cuda_version='12.8',device_name='software_fixture',
                         device_total_bytes=4*1024**3,amp_supported=True)
            result={'status':'ready','runtime_binding':identity,'runtime_sha256':canonical_sha256(identity),
                    'cuda_smoke':{'forward':True,'backward':True,'optimizer':True},'peak_allocated_bytes':100,'peak_reserved_bytes':100,
                    'fixture_provenance':'controlled software outcome; CUDA not run'}
        elif request['operation']=='neural_pilot':
            development=load_development(self.study)
            components=read_json(self.study.path/'components.json')['development']
            cohort=module.compatible_cohort_manifest(development,components)
            result={'status':'ready','pilot_rows':32,'optimizer_steps':20,'forecast_seconds':100,
                    'peak_allocated_bytes':1024**3,'peak_reserved_bytes':2*1024**3,'compatible_cohort':cohort,
                    'pilot_case_ids_sha256':canonical_sha256([value.case_id for value in module.balanced_pilot_rows(development['train'])]),
                    'runtime_binding':request['probe']['runtime_binding'],'runtime_sha256':request['probe']['runtime_sha256'],
                    'fixture_provenance':'controlled software outcome; no GPU optimization'}
        elif request['operation']=='neural_fit':
            directory=Path(request['output_directory']); directory.mkdir()
            for name in self.sources['manifest']['model']['members']:
                (directory/name).write_bytes((Path(self.sources['model_dir'])/name).read_bytes())
            (directory/'model.safetensors').write_bytes(b'CONTROLLED CHECKPOINT; NOT REAL TRAINED WEIGHTS')
            (directory/'config.json').write_text('{"num_labels":2}',encoding='utf-8')
            report={'selected_epoch':1,'selection_partition':'validation','validation_report':{'recall':1,'precision':1,'fpr':0,'raw_threshold':.5},
                    'runtime_binding':request['pilot']['probe']['runtime_binding'],'runtime_sha256':request['pilot']['probe']['runtime_sha256'],
                    'epoch_reports':[], 'peak_allocated_bytes':1024**3,'peak_reserved_bytes':2*1024**3,'fit_seconds':1,
                    'fixture_provenance':'controlled software outcome; no Torch/CUDA fit'}
            record=module.candidate_fit_record(request,directory,report)
            result={'fit_record':record}
        elif request['operation']=='neural_score':
            from test_context_harm_neural_pilot import FixtureTokenizer
            encoded=[module.encode_model_text(ModelText(value['model_input']['target'],tuple(value['model_input']['context'])),FixtureTokenizer(),contextual=request['kind']=='context_neural') for value in request['rows']]
            result={'case_ids':[value['case_id'] for value in request['rows']], 'scores':[.25 if value['supported'] else None for value in encoded],
                    'runtime_binding':read_json(Path(request['candidate_directory'])/'fit-record.json')['runtime_binding'],
                    'runtime_sha256':read_json(Path(request['candidate_directory'])/'fit-record.json')['runtime_sha256'],
                    'coverage':[value['supported'] for value in encoded],'token_coverage':module.aggregate_token_coverage(encoded),
                    'peak_allocated_bytes':0,'peak_reserved_bytes':0}
        elif request['operation']=='neural_attest':
            result={'runtime_binding':request['probe']['runtime_binding'],'runtime_sha256':request['probe']['runtime_sha256']}
        else:
            raise AssertionError('unexpected worker operation')
        return WorkerRecord('ok',None,{**measured(),'deadline_seconds':limits.deadline_seconds},result)
