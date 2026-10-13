"""Strict submitted turns and conservative CAD ancestry reconstruction.

ModelText preserves raw target/verified context for rule observations; feature
consumers apply prepare_model_text. Submitted turns and full source provenance
remain private audit data. Any malformed source edge excludes its whole child
thread; the original SourceRelease is retained for protected-test ownership.
"""
import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from .contracts import (CaseCohort, ConversationInput, HarmCase, HarmError,
                        ModelText, SourceRelease)
from .source import map_labels

MAX_CONTEXT_TURNS = 4
MAX_SUBMITTED_TURNS = 50
MAX_TARGET_CHARACTERS = 10000
MAX_TOTAL_CHARACTERS = 20000
OPAQUE_ID_PATTERN = r'[A-Za-z0-9_-]{1,64}'
_ID = re.compile(OPAQUE_ID_PATTERN, re.ASCII)
_STRUCTURE = frozenset(('conversation_kind', 'conversation_turns', 'target_turn_id'))
_REQUIRED_TURN = frozenset(('turn_id', 'speaker_id', 'text'))
_OPTIONAL_TURN = frozenset(('relative_time_seconds', 'reply_to'))
_GAPS = frozenset(('missing_parent', 'unsupported_parent', 'missing_root_title', 'missing_root_post'))


def _opaque_id(value) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _coverage(*, structured, supplied, preceding, available, used, later=0,
              termination=None, target_present=True, language_supported=True):
    return {
        'structured': structured,
        'target_present': target_present,
        'language_supported': language_supported,
        'supplied_turns': supplied,
        'preceding_turns': preceding,
        'available_context_turns': available,
        'used_context_turns': used,
        'omitted_context_turns': available - used,
        'later_turns_excluded': later,
        'window_limited': available > used,
        'context_missing': available == 0 or termination in _GAPS,
        'termination_reason': termination,
    }


def parse_submission(payload: dict) -> ConversationInput:
    if not isinstance(payload, dict):
        raise HarmError('submission_not_object')
    assumed = 'language' not in payload
    language = payload.get('language', 'en')
    if not isinstance(language, str):
        raise HarmError('language_not_string')
    language = language.strip().lower()
    supported = language == 'en'
    present = _STRUCTURE & payload.keys()
    if present and present != _STRUCTURE:
        raise HarmError('structured_fields_incomplete')
    if not present:
        message = payload.get('message', '')
        if not isinstance(message, str):
            raise HarmError('message_not_string')
        if len(message) > MAX_TARGET_CHARACTERS:
            raise HarmError('target_characters_exceeded')
        message = message.strip()
        coverage = _coverage(structured=False, supplied=0, preceding=0, available=0,
            used=0, termination='no_structured_context', target_present=bool(message),
            language_supported=supported)
        return ConversationInput(None, ModelText(message), (),
                                 coverage, language, assumed)

    kind = payload['conversation_kind']
    if kind not in ('linear', 'reply_thread'):
        raise HarmError('conversation_kind_invalid')
    raw_turns = payload['conversation_turns']
    if not isinstance(raw_turns, list) or not 1 <= len(raw_turns) <= MAX_SUBMITTED_TURNS:
        raise HarmError('conversation_turn_count_invalid')
    target_id = payload['target_turn_id']
    if not _opaque_id(target_id):
        raise HarmError('target_id_invalid')
    turns = []
    indexes = {}
    previous_time = None
    total_characters = 0
    for raw in raw_turns:
        if not isinstance(raw, dict) or not _REQUIRED_TURN <= raw.keys():
            raise HarmError('turn_fields_incomplete')
        if raw.keys() - (_REQUIRED_TURN | _OPTIONAL_TURN):
            raise HarmError('unknown_turn_field')
        turn_id = raw['turn_id']
        if not _opaque_id(turn_id) or turn_id in indexes:
            raise HarmError('turn_id_invalid_or_duplicate')
        if raw['speaker_id'] is not None and not _opaque_id(raw['speaker_id']):
            raise HarmError('speaker_id_invalid')
        text = raw['text']
        if not isinstance(text, str) or not text.strip():
            raise HarmError('turn_text_empty_or_invalid')
        total_characters += len(text)
        if total_characters > MAX_TOTAL_CHARACTERS:
            raise HarmError('conversation_characters_exceeded')
        if 'relative_time_seconds' in raw:
            value = raw['relative_time_seconds']
            if (type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value < 0
                    or (previous_time is not None and value < previous_time)):
                raise HarmError('relative_time_invalid_or_unordered')
            previous_time = value
        if kind == 'linear':
            if 'reply_to' in raw:
                raise HarmError('linear_reply_to_forbidden')
        else:
            if 'reply_to' not in raw:
                raise HarmError('reply_to_required')
            parent = raw['reply_to']
            if parent is not None and (not _opaque_id(parent) or parent not in indexes):
                raise HarmError('reply_to_not_backward')
        indexes[turn_id] = len(turns)
        turns.append(dict(raw))
    if target_id not in indexes:
        raise HarmError('target_not_present')
    target_index = indexes[target_id]
    target = turns[target_index]
    if len(target['text']) > MAX_TARGET_CHARACTERS:
        raise HarmError('target_characters_exceeded')
    if 'message' in payload:
        message = payload['message']
        if not isinstance(message, str) or message.strip() != target['text'].strip():
            raise HarmError('dual_target_disagreement')
    if kind == 'linear':
        ancestors = turns[:target_index]
    else:
        ancestors = []
        parent = target['reply_to']
        while parent is not None:
            ancestor = turns[indexes[parent]]
            ancestors.append(ancestor)
            parent = ancestor['reply_to']
        ancestors.reverse()
    used = ancestors[-MAX_CONTEXT_TURNS:]
    model_input = ModelText(target['text'], tuple(item['text'] for item in used))
    coverage = _coverage(structured=True, supplied=len(turns), preceding=len(ancestors),
        available=len(ancestors), used=len(used), later=len(turns) - target_index - 1,
        termination='no_parent' if not ancestors else None, language_supported=supported)
    return ConversationInput(target_id, model_input, tuple(turns), coverage, language, assumed)


def _limits(settings: dict) -> tuple[int, int, int]:
    if not isinstance(settings, dict) or not isinstance(settings.get('context', {}), dict):
        raise HarmError('context_settings_invalid')
    context = settings.get('context', {})
    values = (context.get('max_turns', MAX_CONTEXT_TURNS),
              context.get('max_target_characters', MAX_TARGET_CHARACTERS),
              context.get('max_total_characters', MAX_TOTAL_CHARACTERS))
    for value, maximum in zip(values, (MAX_CONTEXT_TURNS, MAX_TARGET_CHARACTERS, MAX_TOTAL_CHARACTERS)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise HarmError('context_settings_relax_approved_limits')
    return values


def _check_order(parent, child) -> None:
    if not parent.order or not child.order:
        return
    if len(parent.order) < len(child.order) and child.order[:len(parent.order)] == parent.order:
        return
    # Scalar numeric orders are supported by imported/synthetic chronological records.
    if len(parent.order) == len(child.order) == 1:
        try:
            older, newer = Decimal(parent.order[0]), Decimal(child.order[0])
            if older.is_finite() and newer.is_finite() and older < newer:
                return
        except (InvalidOperation, TypeError):
            pass
    raise HarmError('ordering_contradiction')


def _root_parents(node, records, root_id):
    post = records.get(root_id + '-post')
    title = records.get(root_id + '-title')
    for item in (post, title):
        if item is None:
            continue
        if item.thread_id != node.thread_id:
            raise HarmError('cross_thread_parent')
        # The released root rows have missing root links. Their ID stem and the
        # child's explicit parent/root-link equality confirm the root alias.
        if item.root_id not in (None, root_id):
            raise HarmError('root_metadata_mismatch')
    if post is None:
        return (), 'missing_root_post' if title is not None else 'missing_parent', True
    return tuple(item for item in (post, title) if item is not None), (
        'missing_root_title' if title is None else None), True


def _source_parents(node, records):
    if node.parent_id is None:
        return (), None, False
    parent = records.get(node.parent_id)
    if parent is not None:
        if parent.thread_id != node.thread_id:
            raise HarmError('cross_thread_parent')
        if (parent.case_id.endswith('-post') and node.root_id is not None
                and parent.case_id == node.root_id + '-post'):
            return _root_parents(node, records, node.root_id)
        _check_order(parent, node)
        return (parent,), None, False
    if node.root_id is not None and node.parent_id == node.root_id:
        return _root_parents(node, records, node.root_id)
    return (), 'missing_parent', False


def _audit_graph(records) -> dict[str, set[str]]:
    invalid = defaultdict(set)
    graph = {}
    for node in records.values():
        try:
            parents, _, _ = _source_parents(node, records)
            graph[node.case_id] = tuple(item.case_id for item in parents)
        except HarmError as error:
            invalid[node.thread_id].add(error.reason)
            graph[node.case_id] = ()
    # Iterative DFS audits every source record, including unsupported text and
    # ancestry beyond the model window, without a recursion-depth shortcut.
    state = {}
    for start in graph:
        if state.get(start) == 2:
            continue
        state[start] = 1
        stack = [(start, iter(graph[start]))]
        while stack:
            current, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                state[current] = 2
                stack.pop()
            elif state.get(neighbor) == 1:
                invalid[records[current].thread_id].add('ancestry_cycle')
            elif state.get(neighbor) != 2:
                state[neighbor] = 1
                stack.append((neighbor, iter(graph[neighbor])))
    return invalid


def _ancestry(target, records):
    available = []
    ancestry = []
    current = target
    termination = None
    while True:
        parents, gap, root = _source_parents(current, records)
        if not parents:
            termination = gap or ('no_parent' if current is target else None)
            break
        for parent in parents:
            ancestry.append(parent)
            if not parent.text_supported:
                termination = 'unsupported_parent'
                break
            available.append(parent)
        if termination is not None:
            break
        if root:
            termination = gap
            break
        current = parents[0]
    return tuple(reversed(ancestry)), tuple(reversed(available)), termination


def _decode_source_text(text: str) -> str:
    return text.replace('[linebreak]', '\n')


def build_cases(source: SourceRelease, settings: dict) -> CaseCohort:
    max_turns, max_target, max_total = _limits(settings)
    records = {item.case_id: item for item in source.records}
    if len(records) != len(source.records):
        raise HarmError('source_identity_duplicate')
    invalid = _audit_graph(records)
    primary, diagnostics = [], []
    exclusions = Counter()
    diagnostics_by_reason = Counter()
    omissions = 0
    for target in sorted(source.records, key=lambda item: item.case_id):
        if not target.eligible:
            continue
        label = map_labels(target.labels)
        if target.thread_id in invalid:
            exclusions['invalid_thread'] += 1
            continue
        ancestry, available, termination = _ancestry(target, records)
        used = available[-max_turns:]
        target_text = _decode_source_text(target.text)
        context = tuple(_decode_source_text(item.text) for item in used)
        if len(target_text) > max_target:
            exclusions['target_characters_exceeded'] += 1
            continue
        if len(target_text) + sum(map(len, context)) > max_total:
            exclusions['window_characters_exceeded'] += 1
            continue
        coverage = _coverage(structured=True, supplied=len(ancestry) + 1,
            preceding=len(ancestry), available=len(available), used=len(used), termination=termination)
        omissions += coverage['omitted_context_turns']
        metadata = dict(target.metadata)
        metadata.update({'split': target.split, 'labels': target.labels,
            'context_tags': target.context_tags, 'author_id': target.author_id,
            'parent_id': target.parent_id, 'root_id': target.root_id, 'order': target.order,
            'ancestry_ids': tuple(item.case_id for item in ancestry),
            'available_context_ids': tuple(item.case_id for item in available), 'coverage': coverage})
        case = HarmCase(target.case_id, ModelText(target_text, context),
                        tuple(item.case_id for item in used), target.thread_id, label, metadata)
        if used:
            primary.append(case)
        else:
            diagnostics.append(case)
            diagnostics_by_reason[termination or 'no_usable_predecessor'] += 1
    reasons = Counter(reason for values in invalid.values() for reason in values)
    audit = {
        'source_records': len(source.records),
        'source_threads': len({item.thread_id for item in source.records}),
        'eligible_targets': sum(item.eligible for item in source.records),
        'excluded_threads': len(invalid),
        'excluded_thread_reasons': dict(sorted(reasons.items())),
        'excluded_cases': sum(exclusions.values()),
        'exclusions': dict(sorted(exclusions.items())),
        'primary_cases': len(primary),
        'diagnostic_cases': len(diagnostics),
        'primary_class_counts': dict(sorted(Counter(str(case.label) for case in primary).items())),
        'diagnostic_class_counts': dict(sorted(Counter(str(case.label) for case in diagnostics).items())),
        'diagnostic_reasons': dict(sorted(diagnostics_by_reason.items())),
        'omitted_context_turns': omissions,
        'limits': {'max_turns': max_turns, 'max_target_characters': max_target,
                   'max_total_characters': max_total},
    }
    return CaseCohort(tuple(primary), tuple(diagnostics), source, audit)
