"""Whole-thread ownership, one development allocation, immutable study files."""
import hashlib
import json
import random
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from .contracts import (CaseCohort, FrozenStudy, HarmCase, HarmCriteria, HarmError,
                        ModelText, PRODUCTION_CRITERIA, SourceRelease)
from .integrity import (canonical_bytes, canonical_sha256, publish_stage, read_json,
                        safe_path, sha256, write_json)
from .source import ARCHIVE_SHA, MEMBER_SHA, default_settings, load_source
from ..url_v2.ranges import cache_lock

PRODUCTION_SETTINGS_SHA256 = 'd7ff7bdefc6736c930ed0d2226f417c49ea451dc1995747e7eedc499489ffece'
PARTITIONS = ('train', 'validation', 'calibration')
FRACTIONS = (.7, .15, .15)
PROTOCOL_FILES = ('source.py', 'contracts.py', 'integrity.py', 'conversation.py',
                  'text.py', 'challenge.py', 'protocol.py')


def implementation_hashes() -> dict:
    """LF-normalized code identities survive a Git checkout's CRLF conversion."""
    directory = Path(__file__).parent
    return {name: hashlib.sha256((directory/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name in PROTOCOL_FILES}


class _Union:
    def __init__(self, keys): self.parents = {key: key for key in keys}
    def find(self, key):
        parent = self.parents[key]
        while parent != self.parents[parent]:
            parent = self.parents[parent]
        while key != parent:
            following = self.parents[key]; self.parents[key] = parent; key = following
        return parent
    def join(self, left, right):
        a, b = self.find(left), self.find(right)
        if a != b: self.parents[max(a,b)] = min(a,b)


def _duplicate_pairs(items):
    """Four disjoint 16-bit buckets guarantee candidates for distance <= 3."""
    complete = {}; targets = {}; buckets = defaultdict(list)
    for identity, keys in items:
        key = keys['input_exact']
        if key in complete: yield identity, complete[key]
        else: complete[key] = identity
        key = keys['target_exact']
        if key is not None:
            if key in targets: yield identity, targets[key]
            else: targets[key] = identity
        fingerprint = keys['target_simhash']
        if fingerprint is None: continue
        seen = set()
        for bucket in keys['simhash_buckets']:
            bucket = tuple(bucket)
            for other, bits in buckets[bucket]:
                if other not in seen and (fingerprint ^ bits).bit_count() <= 3:
                    seen.add(other); yield identity, other
            buckets[bucket].append((identity, fingerprint))


def connected_components(cases: tuple[HarmCase,...], source: SourceRelease) -> dict[str,str]:
    from .text import duplicate_keys
    if len({c.case_id for c in cases}) != len(cases):
        raise HarmError('cohort_duplicate_case_identity')
    threads = {c.thread_id for c in cases}; union = _Union(threads)
    authors = {}
    for record in source.records:
        if record.thread_id not in threads or record.author_id is None: continue
        if record.author_id in authors: union.join(record.thread_id, authors[record.author_id])
        else: authors[record.author_id] = record.thread_id
    by_id = {c.case_id: c for c in cases}
    for a,b in _duplicate_pairs((c.case_id,duplicate_keys(c.model_input)) for c in cases):
        union.join(by_id[a].thread_id,by_id[b].thread_id)
    return {c.case_id: 'component-'+canonical_sha256(union.find(c.thread_id))[:24] for c in cases}


def _counts(rows, source):
    by_id = {r.case_id:r for r in source.records}
    return {'cases':len(rows), 'threads':len({c.thread_id for c in rows}),
        'class_counts':{str(label):sum(c.label==label for c in rows) for label in (0,1)},
        'unknown_target_authors':sum(by_id.get(c.case_id) is None or by_id[c.case_id].author_id is None for c in rows)}


def _protected_pool(cohort: CaseCohort, challenge: dict):
    from .text import duplicate_keys
    if challenge.get('schema_version') != 1 or 'cad_case_ids' not in challenge or 'duplicate_keys' not in challenge:
        raise HarmError('challenge_reservation_required')
    source = cohort.source; records = {r.case_id:r for r in source.records}
    test_threads = {r.thread_id for r in source.records if r.split == 'test'}
    test_authors = {r.author_id for r in source.records if r.thread_id in test_threads and r.author_id is not None}
    all_cases = cohort.primary + cohort.diagnostics
    test_all = tuple(c for c in all_cases if c.thread_id in test_threads)
    development = tuple(c for c in all_cases if c.thread_id not in test_threads
                        and records[c.case_id].split in ('train','dev'))
    history = {'before':_counts(development,source)}; purges = {}
    author_threads = {r.thread_id for r in source.records if r.thread_id not in test_threads
                      and r.author_id is not None and r.author_id in test_authors}
    def purge(rows, threads, reason):
        removed = tuple(c for c in rows if c.thread_id in threads)
        purges[reason] = _counts(removed,source)
        return tuple(c for c in rows if c.thread_id not in threads)
    development = purge(development,author_threads,'test_author')
    history['after_test_author'] = _counts(development,source)
    challenge_threads = set()
    for identity in challenge['cad_case_ids']:
        if identity not in records: raise HarmError('challenge_unknown_cad_reference')
        challenge_threads.add(records[identity].thread_id)
    challenge_authors = {r.author_id for r in source.records if r.thread_id in challenge_threads and r.author_id is not None}
    if challenge_threads & test_threads or challenge_authors & test_authors:
        raise HarmError('challenge_overlaps_protected_test_ownership')
    challenge_keys = [('challenge:'+str(i),row['keys']) for i,row in enumerate(challenge['duplicate_keys'])]
    test_keys = [('test:'+c.case_id,duplicate_keys(c.model_input)) for c in test_all]
    for a,b in _duplicate_pairs(test_keys+challenge_keys):
        if a.startswith('challenge:') != b.startswith('challenge:'):
            raise HarmError('challenge_duplicates_protected_test')
    dev_by_id = {'dev:'+c.case_id:c for c in development}
    protected_duplicates = set(); challenge_duplicates = set()
    items = test_keys+challenge_keys+[(key,duplicate_keys(c.model_input)) for key,c in dev_by_id.items()]
    # Components make transitive near-duplicate ownership explicit, including
    # a development chain connected indirectly to a protected input.
    duplicate_union = _Union([identity for identity,_ in items])
    for a,b in _duplicate_pairs(items): duplicate_union.join(a,b)
    held = {duplicate_union.find(identity) for identity,_ in test_keys}
    reviewed = {duplicate_union.find(identity) for identity,_ in challenge_keys}
    if held & reviewed: raise HarmError('challenge_duplicates_protected_test')
    for identity, row in dev_by_id.items():
        component = duplicate_union.find(identity)
        if component in held: protected_duplicates.add(row.thread_id)
        if component in reviewed: challenge_duplicates.add(row.thread_id)
    development = purge(development,protected_duplicates,'test_duplicate')
    history['after_test_duplicate'] = _counts(development,source)
    challenge_threads.update(r.thread_id for r in source.records if r.author_id is not None and r.author_id in challenge_authors)
    development = purge(development,challenge_threads|challenge_duplicates,'challenge_reservation')
    history['after_challenge'] = _counts(development,source)
    retained_ids = {c.case_id for c in development}
    primary_development = tuple(c for c in cohort.primary if c.case_id in retained_ids)
    primary_test = tuple(c for c in cohort.primary if c.thread_id in test_threads)
    diagnostics_test = tuple(c for c in cohort.diagnostics if c.thread_id in test_threads)
    audit = {'schema_version':1, 'history':history, 'purges':purges,
        'development':_counts(primary_development,source), 'primary_test':_counts(primary_test,source),
        'test_diagnostics':_counts(diagnostics_test,source), 'context_audit':cohort.audit,
        'reserved_test_threads':len(test_threads), 'reserved_known_test_authors':len(test_authors),
        'challenge_count':challenge['case_count'], 'source_split_policy':'pool purged original train and dev; preserve test threads'}
    return primary_development,primary_test,diagnostics_test,audit


def audit_cohort(cohort: CaseCohort, challenge: dict, criteria: HarmCriteria) -> dict:
    development,test,diagnostics,audit = _protected_pool(cohort,challenge)
    reasons = []
    if any(sum(c.label==label for c in test)<criteria.test_per_class for label in (0,1)):
        reasons.append('test_class_support')
    if len({c.thread_id for c in test})<criteria.test_threads: reasons.append('test_thread_support')
    try:
        components=connected_components(development,cohort.source)
        parts=allocate_development(development,components,criteria)
        audit['partitions']={name:{**_counts(rows,cohort.source),'components':len({components[c.case_id] for c in rows})}
                             for name,rows in parts.items()}
    except HarmError as error:
        reasons.append(error.reason)
        if hasattr(error,'allocation_report'): audit['failed_allocation']=error.allocation_report
    audit.update(status='ready' if not reasons else 'unavailable',unavailable_reasons=reasons)
    return audit


def allocate_development(cases: tuple[HarmCase,...], components: dict[str,str],
                         criteria: HarmCriteria, seed: int=42) -> dict[str,tuple[HarmCase,...]]:
    if seed!=42: raise HarmError('protocol_seed_must_be_42')
    if any(c.label not in (0,1) for c in cases) or set(components)!= {c.case_id for c in cases}:
        raise HarmError('protocol_labels_or_components_invalid')
    grouped=defaultdict(list)
    for c in cases: grouped[components[c.case_id]].append(c)
    if not cases: raise HarmError('development_empty')
    if max(map(len,grouped.values()))/len(cases)>criteria.max_component_fraction:
        raise HarmError('development_component_too_large')
    rng=random.Random(seed); ties=list(sorted(grouped)); rng.shuffle(ties)
    rank={key:i for i,key in enumerate(ties)}
    order=sorted(grouped,key=lambda key:(-len(grouped[key]),rank[key]))
    totals=[len(cases),sum(c.label==0 for c in cases),sum(c.label==1 for c in cases)]
    goals=[[fraction*total for total in totals] for fraction in FRACTIONS]
    current=[[0,0,0] for _ in PARTITIONS]; assigned={name:[] for name in PARTITIONS}
    for key in order:
        rows=grouped[key]; vector=[len(rows),sum(c.label==0 for c in rows),sum(c.label==1 for c in rows)]
        choices=[]
        for destination in range(3):
            cost=sum(((current[part][col]+(vector[col] if part==destination else 0)-goals[part][col])
                      /max(goals[part][col],1))**2 for part in range(3) for col in range(3))
            choices.append((cost,destination))
        _,destination=min(choices)
        current[destination]=[a+b for a,b in zip(current[destination],vector)]
        assigned[PARTITIONS[destination]].extend(rows)
    report={name:{'cases':len(rows),'class_counts':{str(label):sum(c.label==label for c in rows) for label in (0,1)},
                  'components':len({components[c.case_id] for c in rows})} for name,rows in assigned.items()}
    def failure(reason):
        error=HarmError(reason); error.allocation_report=report; raise error
    for name, minimum in zip(PARTITIONS,(criteria.train_per_class,criteria.validation_per_class,criteria.calibration_per_class)):
        rows=assigned[name]
        if any(sum(c.label==label for c in rows)<minimum for label in (0,1)):
            failure('greedy_allocation_class_support_'+name)
        if name!='train' and len({components[c.case_id] for c in rows})<criteria.development_components:
            failure('greedy_allocation_component_support_'+name)
    return {name:tuple(sorted(rows,key=lambda c:c.case_id)) for name,rows in assigned.items()}


def serialize_case(case: HarmCase) -> dict:
    return asdict(case)


def deserialize_case(value: dict) -> HarmCase:
    try:
        if set(value)!= {'case_id','model_input','context_ids','thread_id','label','metadata'}:
            raise HarmError('derived_case_schema_invalid')
        model=value['model_input']
        if (set(model)!= {'target','context'} or not isinstance(model['target'],str)
            or not isinstance(model['context'],list) or any(not isinstance(v,str) for v in model['context'])
            or type(value['label']) is not int or value['label'] not in (0,1)):
            raise HarmError('derived_case_schema_invalid')
        return HarmCase(value['case_id'],ModelText(model['target'],tuple(model['context'])),
            tuple(value['context_ids']),value['thread_id'],value['label'],value['metadata'])
    except (TypeError,KeyError) as error: raise HarmError('derived_case_schema_invalid') from error


def read_cases(path: Path) -> tuple[HarmCase,...]:
    if path.stat().st_size>64*1024*1024: raise HarmError('derived_partition_oversized')
    try:
        rows=tuple(deserialize_case(json.loads(line)) for line in path.read_text(encoding='utf-8').splitlines() if line)
        if len({c.case_id for c in rows})!=len(rows): raise HarmError('derived_partition_duplicate_identity')
        return rows
    except (ValueError,UnicodeError) as error:
        if isinstance(error,HarmError): raise
        raise HarmError('derived_partition_invalid') from error


def _freeze_cohort(root: Path, cohort: CaseCohort, settings: dict, challenge: dict,
                   *, criteria: HarmCriteria=PRODUCTION_CRITERIA, synthetic: bool=False) -> FrozenStudy:
    root=Path(root).resolve(); root.mkdir(parents=True,exist_ok=True)
    if not synthetic and (criteria!=PRODUCTION_CRITERIA or canonical_sha256(settings)!=PRODUCTION_SETTINGS_SHA256):
        raise HarmError('protocol_settings_not_production')
    with cache_lock(root/'protocol-lock'):
        output=root/'v1'
        if output.exists(): raise HarmError('frozen_study_already_exists')
        audit=audit_cohort(cohort,challenge,criteria)
        if audit['status']!='ready': raise HarmError('protocol_unavailable:'+','.join(audit['unavailable_reasons']))
        development,test,diagnostics,_=_protected_pool(cohort,challenge)
        components=connected_components(development,cohort.source)
        parts=allocate_development(development,components,criteria)
        final_components=connected_components(test+diagnostics,cohort.source)
        if not synthetic:
            review=read_json(root/'codebook-review.json')
            if (review.get('status')!='consistent' or review.get('archive_sha256')!=ARCHIVE_SHA
                or review.get('member_sha256')!=MEMBER_SHA
                or review.get('codebook_sha256')!=sha256(root/'source/cad_codebook_april2021.pdf')):
                raise HarmError('codebook_review_required_or_changed')
        binding={'schema_version':1,'task':'english_directed_abuse','status':'frozen',
            'synthetic':synthetic,'criteria':asdict(criteria),'settings':settings,
            'config_sha256':canonical_sha256(settings),'source':cohort.source.provenance,
            'code_hashes':implementation_hashes(),'challenge_sha256':canonical_sha256(challenge),
            'challenge_reservation_sha256':sha256(root/'challenge/reservation.json') if not synthetic else None,
            'source_manifest_sha256':sha256(root/'source/manifest.json') if not synthetic else None,
            'codebook_review_sha256':sha256(root/'codebook-review.json') if not synthetic else None,
            'allocation':{'seed':42,'fractions':list(FRACTIONS),'method':'largest first; one seed tie order; squared normalized row and class deviations'},
            'audit':audit,'case_hashes':{name:canonical_sha256([serialize_case(c) for c in rows])
                for name,rows in {**parts,'test':test,'diagnostics':diagnostics}.items()},
            'tokenizer_spec':__import__('sentinel.context_harm.text',fromlist=['TOKENIZER_SPEC']).TOKENIZER_SPEC,
            'models_trained':False,'final_test_scored':False}
        stage=Path(tempfile.mkdtemp(prefix='.protocol-stage-',dir=root))
        try:
            write_json(stage/'study.json',binding)
            write_json(stage/'components.json',{'development':components,'test':final_components})
            for name,rows in {**parts,'test':test,'diagnostics':diagnostics}.items():
                with (stage/(name+'.jsonl')).open('xb') as stream:
                    for case in rows: stream.write(canonical_bytes(serialize_case(case))+b'\n')
            published=publish_stage(stage,output,{p.name:sha256(p) for p in stage.iterdir()})
            return FrozenStudy(output,{k:v for k,v in published.items() if k!='manifest_sha256'})
        finally:
            if stage.exists() and stage.resolve().parent==root: shutil.rmtree(stage)


def freeze_study(root: Path, settings: dict) -> FrozenStudy:
    root=Path(root).resolve()
    if not (root/'challenge/reservation.json').exists(): raise HarmError('challenge_reservation_required')
    from .challenge import challenge_reservation
    from .conversation import build_cases
    reservation=challenge_reservation(root)
    source=load_source(root,settings)
    return _freeze_cohort(root,build_cases(source,settings),settings,reservation)


def verify_study(study: FrozenStudy) -> dict:
    path=Path(study.path).resolve(); manifest=read_json(path/'manifest.json')
    expected={'study.json','components.json','train.jsonl','validation.jsonl','calibration.jsonl','test.jsonl','diagnostics.jsonl'}
    if (manifest!=study.manifest or manifest.get('schema_version')!=1
        or set(manifest.get('members',{}))!=expected): raise HarmError('study_manifest_changed')
    for name,digest in manifest['members'].items():
        if sha256(safe_path(path,name))!=digest: raise HarmError('study_member_changed')
    binding=read_json(path/'study.json',max_bytes=4*1024*1024)
    if binding.get('code_hashes')!=implementation_hashes(): raise HarmError('study_implementation_changed')
    if canonical_sha256(binding.get('settings'))!=binding.get('config_sha256'):
        raise HarmError('study_settings_changed')
    if not binding.get('synthetic'):
        if binding['config_sha256']!=PRODUCTION_SETTINGS_SHA256: raise HarmError('study_settings_not_production')
        root=path.parent
        for relative,field in (('source/manifest.json','source_manifest_sha256'),
                               ('codebook-review.json','codebook_review_sha256'),
                               ('challenge/reservation.json','challenge_reservation_sha256')):
            if sha256(root/relative)!=binding.get(field): raise HarmError('study_source_or_challenge_changed')
        load_source(root,binding['settings'])
        from .challenge import challenge_reservation
        if canonical_sha256(challenge_reservation(root))!=binding['challenge_sha256']:
            raise HarmError('study_challenge_changed')
    return binding


def load_development(study: FrozenStudy) -> dict[str,tuple[HarmCase,...]]:
    verify_study(study)
    return {name:read_cases(Path(study.path)/(name+'.jsonl')) for name in PARTITIONS}


def assert_fitting_allowed(study: FrozenStudy) -> None:
    verify_study(study)
    if (Path(study.path).resolve().parent/'final-access.json').exists():
        raise HarmError('fitting_forbidden_after_final_access')
