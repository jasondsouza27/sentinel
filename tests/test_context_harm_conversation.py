"""Invented conversations check structure and coverage, never research accuracy."""
import importlib
import unittest
from dataclasses import replace

from sentinel.context_harm.contracts import CadUtterance, HarmError, SourceRelease


def utterance(case_id, *, parent=None, root=None, thread='thread', order=('1',),
              text='A plain invented statement.', eligible=False, supported=True,
              labels=('Neutral',), metadata=None):
    return CadUtterance(case_id, thread, parent, root, None, order, text, 'train',
                        labels, (), eligible, supported, metadata or {})


def release(*records):
    return SourceRelease(tuple(records), {'fixture': True})


def turn(turn_id, text='An invented statement.', **extra):
    item = dict(turn_id=turn_id, speaker_id=None, text=text)
    item.update(extra)
    return item


def linear(turns=None, target='t2', **extra):
    return dict(conversation_kind='linear', conversation_turns=turns or [
        turn('t1', 'Earlier words'), turn('t2', 'Selected words'),
        turn('t3', 'future threat')], target_turn_id=target, **extra)


class ConversationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.conversation')
        except ModuleNotFoundError:
            self.fail('Task 2 conversation interfaces are not implemented')

    def test_linear_target_excludes_later_turns(self):
        request = self.api.parse_submission(linear())
        self.assertEqual(request.target_id, 't2')
        self.assertEqual(request.model_input.target, 'Selected words')
        self.assertEqual(request.model_input.context, ('Earlier words',))
        self.assertEqual(request.coverage['later_turns_excluded'], 1)
        self.assertEqual(len(request.turns), 3)

    def test_linear_window_uses_four_most_recent_predecessors(self):
        turns = [turn('t' + str(i), 'turn ' + str(i)) for i in range(7)]
        request = self.api.parse_submission(linear(turns, 't6'))
        self.assertEqual(request.model_input.context, ('turn 2', 'turn 3', 'turn 4', 'turn 5'))
        self.assertEqual(request.coverage['available_context_turns'], 6)
        self.assertEqual(request.coverage['omitted_context_turns'], 2)

    def test_reply_thread_follows_only_backward_ancestor_chain(self):
        turns = [turn('a', 'root', reply_to=None),
                 turn('b', 'sibling', reply_to='a'),
                 turn('c', 'parent', reply_to='a'),
                 turn('d', 'target', reply_to='c'),
                 turn('e', 'later', reply_to='d')]
        request = self.api.parse_submission(dict(conversation_kind='reply_thread',
            conversation_turns=turns, target_turn_id='d'))
        self.assertEqual(request.model_input.context, ('root', 'parent'))
        self.assertEqual(request.coverage['later_turns_excluded'], 1)

    def test_reply_thread_requires_explicit_nullable_parent(self):
        payload = dict(conversation_kind='reply_thread', conversation_turns=[turn('a')], target_turn_id='a')
        with self.assertRaises(HarmError):
            self.api.parse_submission(payload)

    def test_reply_thread_rejects_forward_self_missing_and_nonstring_parents(self):
        for parent in ('b', 'a', 'missing', 2, False, ''):
            with self.subTest(parent=parent), self.assertRaises(HarmError):
                self.api.parse_submission(dict(conversation_kind='reply_thread',
                    conversation_turns=[turn('a', reply_to=parent), turn('b', reply_to=None)],
                    target_turn_id='a'))

    def test_linear_rejects_reply_to_even_when_null(self):
        with self.assertRaises(HarmError):
            self.api.parse_submission(linear([turn('t2', reply_to=None)]))

    def test_partial_structured_fields_are_rejected(self):
        complete = linear()
        for missing in ('conversation_kind', 'conversation_turns', 'target_turn_id'):
            payload = {key: value for key, value in complete.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaises(HarmError):
                self.api.parse_submission(payload)

    def test_unknown_turn_field_is_rejected(self):
        with self.assertRaises(HarmError):
            self.api.parse_submission(linear([turn('t2', annotation='gold label')]))

    def test_turns_require_id_nullable_speaker_and_nonempty_text(self):
        for missing in ('turn_id', 'speaker_id', 'text'):
            item = turn('t2')
            item.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(HarmError):
                self.api.parse_submission(linear([item]))
        for text in ('', '  \n\t', None, 4):
            with self.subTest(text=text), self.assertRaises(HarmError):
                self.api.parse_submission(linear([turn('t2', text)]))

    def test_turn_id_accepts_ascii_opaque_boundary(self):
        value = 'A' * 64
        request = self.api.parse_submission(linear([turn(value)], value))
        self.assertEqual(request.target_id, value)

    def test_invalid_turn_ids_and_speaker_ids_are_rejected(self):
        for value in ('', 'A' * 65, 'two words', 'é', 'a/b', '\n', None, 12, True):
            with self.subTest(value=value), self.assertRaises(HarmError):
                self.api.parse_submission(linear([turn(value)], value))
        for value in ('two words', 'é', 'A' * 65, 2):
            with self.subTest(speaker=value), self.assertRaises(HarmError):
                self.api.parse_submission(linear([turn('t2', speaker_id=value)]))

    def test_unique_ids_and_present_target_are_required(self):
        for payload in (linear([turn('t2'), turn('t2')]), linear([turn('other')])):
            with self.assertRaises(HarmError):
                self.api.parse_submission(payload)

    def test_fifty_turns_are_accepted_and_fifty_one_rejected(self):
        turns = [turn('t' + str(i), 'x') for i in range(51)]
        self.assertEqual(len(self.api.parse_submission(linear(turns[:50], 't0')).turns), 50)
        with self.assertRaises(HarmError):
            self.api.parse_submission(linear(turns, 't0'))

    def test_turn_array_and_kind_must_have_supported_types(self):
        for value in ([], None, {}, 'not an array', [None]):
            payload = linear()
            payload['conversation_turns'] = value
            with self.subTest(value=value), self.assertRaises(HarmError):
                self.api.parse_submission(payload)
        for kind in ('other', None, 3, ' LINEAR '):
            payload = linear()
            payload['conversation_kind'] = kind
            with self.subTest(kind=kind), self.assertRaises(HarmError):
                self.api.parse_submission(payload)

    def test_total_character_boundary_counts_later_supplied_turns(self):
        request = linear([turn('t2', 'a' * 10000), turn('future', 'b' * 10000)])
        self.assertEqual(len(self.api.parse_submission(request).model_input.target), 10000)
        request['conversation_turns'][1]['text'] += 'b'
        with self.assertRaises(HarmError):
            self.api.parse_submission(request)

    def test_target_character_limit_is_independent_of_total(self):
        with self.assertRaises(HarmError):
            self.api.parse_submission(linear([turn('t2', 'a' * 10001)]))

    def test_relative_timestamps_allow_missing_equal_and_increasing_times(self):
        turns = [turn('a', relative_time_seconds=0), turn('b'),
                 turn('t2', relative_time_seconds=0.0), turn('d', relative_time_seconds=0.5)]
        self.assertEqual(len(self.api.parse_submission(linear(turns)).turns), 4)

    def test_relative_timestamps_reject_nonfinite_negative_boolean_and_order_conflicts(self):
        for value in (-1, float('nan'), float('inf'), float('-inf'), True, None, '2'):
            with self.subTest(value=value), self.assertRaises(HarmError):
                self.api.parse_submission(linear([turn('t2', relative_time_seconds=value)]))
        with self.assertRaises(HarmError):
            self.api.parse_submission(linear([turn('a', relative_time_seconds=2), turn('gap'),
                                             turn('t2', relative_time_seconds=1)]))

    def test_legacy_message_dual_target_allows_only_outer_trim_equivalence(self):
        request = self.api.parse_submission(linear(message='  Selected words\n'))
        self.assertEqual(request.model_input.target, 'Selected words')
        for message in ('selected words', 'Selected  words', 'Another target', None):
            with self.subTest(message=message), self.assertRaises(HarmError):
                self.api.parse_submission(linear(message=message))

    def test_declared_language_is_normalized_without_claiming_detection(self):
        english = self.api.parse_submission(linear(language=' EN '))
        self.assertEqual(english.language, 'en')
        self.assertFalse(english.language_assumed)
        self.assertTrue(english.coverage['language_supported'])
        other = self.api.parse_submission(linear(language=' Fr '))
        self.assertEqual(other.language, 'fr')
        self.assertFalse(other.coverage['language_supported'])
        self.assertFalse(other.language_assumed)
        missing = self.api.parse_submission(linear())
        self.assertEqual(missing.language, 'en')
        self.assertTrue(missing.language_assumed)
        with self.assertRaises(HarmError):
            self.api.parse_submission(linear(language=3))

    def test_legacy_selected_message_has_explicit_missing_context(self):
        request = self.api.parse_submission({'message': 'hello', 'conversation': 'arbitrary flat earlier text'})
        self.assertEqual(request.model_input.target, 'hello')
        self.assertEqual(request.model_input.context, ())
        self.assertEqual(request.turns, ())
        self.assertIsNone(request.target_id)
        self.assertTrue(request.coverage['context_missing'])
        self.assertTrue(request.coverage['target_present'])

    def test_legacy_conversation_without_selected_message_has_no_learned_target(self):
        request = self.api.parse_submission({'conversation': 'only a flat conversation'})
        self.assertEqual(request.model_input.target, '')
        self.assertFalse(request.coverage['target_present'])
        self.assertEqual(request.model_input.context, ())

    def test_legacy_message_character_limit_is_enforced(self):
        self.assertEqual(len(self.api.parse_submission({'message': 'x' * 10000}).model_input.target), 10000)
        with self.assertRaises(HarmError):
            self.api.parse_submission({'message': 'x' * 10001})

    def test_literal_quotation_and_local_speaker_are_preserved_only_in_turn_audit(self):
        quoted = 'She reported "you are stupid".'
        request = self.api.parse_submission(linear([turn('t2', quoted, speaker_id='local_a')]))
        self.assertEqual(request.model_input.target, quoted)
        self.assertNotIn('local_a', request.model_input.target)
        self.assertEqual(request.turns[0]['speaker_id'], 'local_a')

    def test_payload_mutation_does_not_change_parsed_turn_snapshot(self):
        payload = linear()
        request = self.api.parse_submission(payload)
        payload['conversation_turns'][0]['text'] = 'changed'
        self.assertEqual(request.turns[0]['text'], 'Earlier words')

    def test_parser_preserves_raw_destinations_and_usernames_for_rule_observations(self):
        request = self.api.parse_submission(linear([turn('t2', '@Alice said https://one.example!')]))
        self.assertEqual(request.model_input.target, '@Alice said https://one.example!')
        self.assertEqual(request.turns[0]['text'], '@Alice said https://one.example!')

    def test_source_root_alias_resolves_title_before_body(self):
        source = release(utterance('root-title', order=('title',), text='Root title'),
                         utterance('root-post', order=('post',), text='Root body'),
                         utterance('target', parent='root', root='root', order=('thread', '1'), eligible=True))
        case = self.api.build_cases(source, {}).primary[0]
        self.assertEqual(case.context_ids, ('root-title', 'root-post'))
        self.assertEqual(case.model_input.context, ('Root title', 'Root body'))

    def test_source_root_alias_requires_matching_root_link(self):
        source = release(utterance('root-title', text='Root title'),
                         utterance('root-post', text='Root body'),
                         utterance('target', parent='root', root='different', order=('2',), eligible=True))
        cohort = self.api.build_cases(source, {})
        self.assertEqual(len(cohort.primary), 0)
        self.assertEqual(cohort.diagnostics[0].model_input.context, ())

    def test_source_cross_thread_root_alias_excludes_affected_thread(self):
        source = release(utterance('root-post', thread='other'),
                         utterance('target', parent='root', root='root', eligible=True))
        cohort = self.api.build_cases(source, {})
        self.assertEqual(cohort.primary, ())
        self.assertEqual(cohort.diagnostics, ())
        self.assertEqual(cohort.audit['excluded_thread_reasons']['cross_thread_parent'], 1)

    def test_source_missing_parent_is_diagnostic_not_arbitrary_previous_row(self):
        source = release(utterance('unrelated', order=('1',), text='Arbitrary earlier sibling'),
                         utterance('target', parent='absent', order=('2',), eligible=True))
        cohort = self.api.build_cases(source, {})
        self.assertEqual(cohort.primary, ())
        self.assertEqual(cohort.diagnostics[0].model_input.context, ())
        self.assertEqual(cohort.diagnostics[0].metadata['coverage']['termination_reason'], 'missing_parent')

    def test_source_unsupported_intermediate_stops_chain_without_jumping(self):
        for marker in ('exclude_image', 'exclude_lang', 'exclude_empty'):
            source = release(utterance('older', order=('0',), text='Older usable words'),
                             utterance('parent', parent='older', order=('1',), supported=False,
                                       metadata={'excluded_splits': [marker]}),
                             utterance('target', parent='parent', order=('2',), eligible=True))
            with self.subTest(marker=marker):
                cohort = self.api.build_cases(source, {})
                self.assertEqual(cohort.primary, ())
                self.assertEqual(cohort.diagnostics[0].model_input.context, ())
                self.assertEqual(cohort.diagnostics[0].metadata['coverage']['termination_reason'], 'unsupported_parent')

    def test_source_available_parent_before_missing_ancestor_remains_context_with_gap(self):
        source = release(utterance('parent', parent='missing', order=('1',), text='Immediate parent'),
                         utterance('target', parent='parent', order=('2',), eligible=True))
        case = self.api.build_cases(source, {}).primary[0]
        self.assertEqual(case.model_input.context, ('Immediate parent',))
        self.assertTrue(case.metadata['coverage']['context_missing'])
        self.assertEqual(case.metadata['coverage']['termination_reason'], 'missing_parent')

    def test_source_root_body_unavailable_does_not_skip_to_title(self):
        source = release(utterance('root-title', text='Usable title'),
                         utterance('root-post', supported=False),
                         utterance('target', parent='root', root='root', eligible=True))
        self.assertEqual(self.api.build_cases(source, {}).diagnostics[0].model_input.context, ())

    def test_source_window_uses_four_recent_ancestors_and_audits_omitted_ancestry(self):
        nodes = [utterance('p' + str(i), parent=None if i == 0 else 'p' + str(i - 1),
                           order=(str(i),), text='ancestor ' + str(i)) for i in range(6)]
        nodes.append(utterance('target', parent='p5', order=('6',), eligible=True))
        case = self.api.build_cases(release(*nodes), {}).primary[0]
        self.assertEqual(case.model_input.context, ('ancestor 2', 'ancestor 3', 'ancestor 4', 'ancestor 5'))
        self.assertEqual(case.context_ids, ('p2', 'p3', 'p4', 'p5'))
        self.assertEqual(case.metadata['ancestry_ids'], ('p0', 'p1', 'p2', 'p3', 'p4', 'p5'))
        self.assertEqual(case.metadata['coverage']['omitted_context_turns'], 2)

    def test_source_tree_path_order_is_not_lexicographic_sibling_order(self):
        source = release(utterance('parent', order=('thread', '10'), text='Verified parent'),
                         utterance('target', parent='parent', order=('thread', '10', '2'), eligible=True))
        self.assertEqual(self.api.build_cases(source, {}).primary[0].context_ids, ('parent',))

    def test_source_order_contradiction_excludes_entire_thread_including_independent_target(self):
        source = release(utterance('bad_parent', order=('thread', '1', '2')),
                         utterance('bad', parent='bad_parent', order=('thread', '1'), eligible=True),
                         utterance('otherwise_root', eligible=True),
                         utterance('good_parent', thread='good', order=('1',)),
                         utterance('good', parent='good_parent', thread='good', order=('2',), eligible=True))
        cohort = self.api.build_cases(source, {})
        self.assertEqual(tuple(case.case_id for case in cohort.primary), ('good',))
        self.assertEqual(cohort.diagnostics, ())
        self.assertEqual(cohort.audit['excluded_thread_reasons']['ordering_contradiction'], 1)
        self.assertEqual(cohort.audit['excluded_cases'], 2)
        self.assertIs(cohort.source, source)

    def test_source_cross_thread_parent_excludes_entire_child_thread(self):
        source = release(utterance('parent', thread='other', order=('1',)),
                         utterance('target', parent='parent', order=('2',), eligible=True),
                         utterance('same_thread_root', eligible=True))
        cohort = self.api.build_cases(source, {})
        self.assertEqual(cohort.primary, ())
        self.assertEqual(cohort.diagnostics, ())
        self.assertEqual(cohort.audit['excluded_cases'], 2)

    def test_source_cycles_exclude_thread_even_when_beyond_model_window(self):
        nodes = [utterance('p' + str(i), parent='p' + str((i + 1) % 6), order=()) for i in range(6)]
        nodes.append(utterance('target', parent='p0', order=(), eligible=True))
        cohort = self.api.build_cases(release(*nodes), {})
        self.assertEqual(cohort.primary, ())
        self.assertEqual(cohort.diagnostics, ())
        self.assertEqual(cohort.audit['excluded_thread_reasons']['ancestry_cycle'], 1)

    def test_source_raw_characters_are_capped_before_masking(self):
        target = 'https://one.example/' + 'a' * 10000
        cohort = self.api.build_cases(release(utterance('p'),
            utterance('target', parent='p', order=('2',), text=target, eligible=True)), {})
        self.assertEqual(cohort.primary, ())
        self.assertEqual(cohort.audit['exclusions']['target_characters_exceeded'], 1)

    def test_source_combined_window_character_boundary(self):
        source = release(utterance('p', text='p' * 10000),
                         utterance('target', parent='p', order=('2',), text='t' * 10000, eligible=True))
        self.assertEqual(len(self.api.build_cases(source, {}).primary), 1)
        oversized = release(replace(source.records[0], text='p' * 10001), source.records[1])
        cohort = self.api.build_cases(oversized, {})
        self.assertEqual(cohort.primary, ())
        self.assertEqual(cohort.audit['exclusions']['window_characters_exceeded'], 1)

    def test_source_omitted_ancestor_size_does_not_limit_four_turn_window(self):
        nodes = [utterance('p0', order=('0',), text='x' * 20001)]
        nodes += [utterance('p' + str(i), parent='p' + str(i - 1), order=(str(i),), text='small')
                  for i in range(1, 5)]
        nodes.append(utterance('target', parent='p4', order=('5',), eligible=True))
        self.assertEqual(len(self.api.build_cases(release(*nodes), {}).primary), 1)

    def test_source_linebreaks_and_quoted_text_preserve_words(self):
        source = release(utterance('p', text='Someone said "stop"[linebreak]and waited.'),
                         utterance('target', parent='p', order=('2',), text='A[linebreak]B', eligible=True))
        case = self.api.build_cases(source, {}).primary[0]
        self.assertEqual(case.model_input.context, ('Someone said "stop"\nand waited.',))
        self.assertEqual(case.model_input.target, 'A\nB')
        self.assertEqual(source.records[0].text, 'Someone said "stop"[linebreak]and waited.')

    def test_source_gold_annotations_are_audit_metadata_only(self):
        target = utterance('target', parent='p', order=('2',), text='Actual selected text', eligible=True,
                           labels=('PersonDirectedAbuse',), metadata={'highlight': 'gold explanation'})
        target = replace(target, author_id='private_author', context_tags=('CurrentContent',))
        case = self.api.build_cases(release(utterance('p'), target), {}).primary[0]
        self.assertEqual(case.label, 1)
        self.assertEqual(case.model_input.target, 'Actual selected text')
        self.assertNotIn('gold explanation', repr(case.model_input))
        self.assertNotIn('private_author', repr(case.model_input))
        self.assertNotIn('CurrentContent', repr(case.model_input))
        self.assertEqual(case.metadata['context_tags'], ('CurrentContent',))

    def test_source_context_only_record_never_becomes_labelled_target(self):
        cohort = self.api.build_cases(release(utterance('context', eligible=False),
            utterance('target', parent='context', order=('2',), eligible=True)), {})
        self.assertEqual(tuple(case.case_id for case in cohort.primary), ('target',))
        self.assertEqual(cohort.audit['eligible_targets'], 1)

    def test_context_settings_cannot_relax_approved_caps(self):
        source = release(utterance('target', eligible=True))
        for context in ({'max_turns': 5}, {'max_target_characters': 10001},
                        {'max_total_characters': 20001}, {'max_turns': True}):
            with self.subTest(context=context), self.assertRaises(HarmError):
                self.api.build_cases(source, {'context': context})

    def test_source_model_text_preserves_raw_context_for_phrase_baseline(self):
        source = release(utterance('p', text='@Earlier links https://one.example.'),
                         utterance('target', parent='p', order=('2',),
                                   text='@Selected links https://two.example.', eligible=True))
        case = self.api.build_cases(source, {}).primary[0]
        self.assertEqual(case.model_input.target, '@Selected links https://two.example.')
        self.assertEqual(case.model_input.context, ('@Earlier links https://one.example.',))

    def test_finite_integer_relative_time_does_not_overflow_float_validation(self):
        try:
            request = self.api.parse_submission(linear([turn('t2', relative_time_seconds=10 ** 400)]))
        except OverflowError:
            self.fail('Finite JSON integer time must not overflow float validation')
        self.assertEqual(request.turns[0]['relative_time_seconds'], 10 ** 400)
