import hashlib
import http.client
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from context_harm_fixtures import cad_row, tsv_bytes, archive_bytes

URL = 'https://zenodo.org/api/records/4881008/files/data.zip/content'


class Response(io.BytesIO):
    def __init__(self, body=b'abcdefgh', *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def geturl(self):
        return URL


class InterruptedBufferedBody(io.RawIOBase):
    def __init__(self):
        self.calls = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        self.calls += 1
        if self.calls == 1:
            buffer[:3] = b'abc'
            return 3
        raise TimeoutError('private error content')


class SourceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.source = importlib.import_module('sentinel.context_harm.source')
            self.transport = importlib.import_module('sentinel.context_harm.transport')
            self.contracts = importlib.import_module('sentinel.context_harm.contracts')
            self.integrity = importlib.import_module('sentinel.context_harm.integrity')
        except ModuleNotFoundError as error:
            if error.name.startswith('sentinel.context_harm'):
                self.fail('The approved contextual-harm ingestion feature is not implemented')
            raise
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.error = self.contracts.HarmError

    def session(self, *, budget=32, deadline=120):
        return self.transport.AcquisitionSession(self.root / 'cache', {
            'allow_hosts': ['zenodo.org'], 'max_received_body_bytes': budget,
            'deadline_seconds': deadline, 'max_attempts': 1,
        })

    def fetch(self, session, *, digest=None, maximum=8):
        return session.fetch(URL, session.root / 'data.zip', resource='archive',
                             max_bytes=maximum,
                             expected_sha256=digest or hashlib.sha256(b'abcdefgh').hexdigest(),
                             expected_size=8)

    def test_quoted_missing_metadata_does_not_modify_quoted_text(self):
        rows = [cad_row('missing', author='"NA"', root='"NA"'),
                cad_row('quoted', text='Someone said "stop".')]
        result = {r.case_id: r for r in self.source.coalesce_rows(rows)}
        self.assertIsNone(result['missing'].author_id)
        self.assertIsNone(result['missing'].root_id)
        self.assertEqual(result['quoted'].text, 'Someone said "stop".')

    def test_deleted_author_markers_are_not_shared_people(self):
        rows = [cad_row(str(i), author=value) for i, value in
                enumerate(('', 'NA', 'nan', 'None', '[deleted]', '"[removed]"'))]
        self.assertEqual([r.author_id for r in self.source.coalesce_rows(rows)], [None] * 6)

    def test_binary_task_preserves_counter_speech_and_non_hateful_slur(self):
        for labels, expected in [(('Neutral',), 0), (('Slur',), 0),
                                 (('CounterSpeech', 'Slur'), 0),
                                 (('IdentityDirectedAbuse',), 1),
                                 (('AffiliationDirectedAbuse',), 1),
                                 (('CounterSpeech', 'PersonDirectedAbuse'), 1)]:
            with self.subTest(labels=labels):
                self.assertEqual(self.source.map_labels(labels), expected)

    def test_invalid_label_sets_fail_before_binary_assignment(self):
        for labels in [(), ('Unknown',), ('Neutral', 'PersonDirectedAbuse'),
                       ('Neutral', 'CounterSpeech')]:
            with self.subTest(labels=labels), self.assertRaises(self.error):
                self.source.map_labels(labels)

    def test_multiple_annotations_become_one_target_with_all_tags(self):
        result = self.source.coalesce_rows([
            cad_row(label='PersonDirectedAbuse', context='CurrentContent'),
            cad_row(label='CounterSpeech', context='PreviousContent')])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].labels, ('CounterSpeech', 'PersonDirectedAbuse'))
        self.assertEqual(result[0].context_tags, ('CurrentContent', 'PreviousContent'))
        self.assertEqual(result[0].metadata['annotation_rows'], 2)

    def test_conflicting_utterance_identity_or_text_stops_admission(self):
        for key, value in [('meta_text', 'Different text'), ('info_thread.id', 'other'),
                           ('info_id.parent', 'other'), ('meta_author', 'other'),
                           ('info_id.link', 'other'), ('info_order', '2'), ('split', 'test')]:
            row = cad_row(label='PersonDirectedAbuse')
            changed = dict(row, **{key: value})
            with self.subTest(key=key), self.assertRaises(self.error):
                self.source.coalesce_rows([row, changed])

    def test_source_exclusions_do_not_become_training_targets(self):
        records = self.source.coalesce_rows([
            cad_row('bot', split='exclude_bot'), cad_row('empty', split='exclude_empty', text=''),
            cad_row('image', split='exclude_image'), cad_row('language', split='exclude_lang')])
        self.assertFalse(any(record.eligible for record in records))
        self.assertTrue(records[0].text_supported)
        self.assertFalse(any(record.text_supported for record in records[1:]))

    def test_tsv_quote_none_and_complete_schema(self):
        path = self.root / 'cases.tsv'
        path.write_bytes(tsv_bytes([cad_row(text='An "actual quotation" here.')]))
        self.assertEqual(self.source.read_cad_tsv(path)[0].text, 'An "actual quotation" here.')
        path.write_text('info_id\tmeta_text\ncase\ttext\n', encoding='utf-8')
        with self.assertRaises(self.error):
            self.source.read_cad_tsv(path)

    def test_wrong_archive_member_hash_or_inflated_size_is_rejected(self):
        body = archive_bytes([cad_row()])
        path = self.root / 'data.zip'; path.write_bytes(body)
        pin = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
               'member': 'data/cad_v1_1.tsv',
               'member_sha256': hashlib.sha256(tsv_bytes([cad_row()])).hexdigest()}
        result = self.source.verify_archive(path, pin)
        self.assertEqual(result['tsv'], tsv_bytes([cad_row()]))
        with self.assertRaises(self.error):
            self.source.verify_archive(path, dict(pin, member_sha256='0' * 64))
        with self.assertRaises(self.error):
            self.source.verify_archive(path, pin, max_member_bytes=10)
        with self.assertRaises(self.error):
            self.source.verify_archive(path, dict(pin, member='data/not-present.tsv'))

    def test_zip_path_escape_is_rejected_without_writing_outside_root(self):
        body = archive_bytes([cad_row()], extra={'../escape.txt': b'no'})
        path = self.root / 'bad.zip'; path.write_bytes(body)
        pin = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
               'member': 'data/cad_v1_1.tsv',
               'member_sha256': hashlib.sha256(tsv_bytes([cad_row()])).hexdigest()}
        with self.assertRaises(self.error):
            self.source.verify_archive(path, pin)
        self.assertFalse((self.root.parent / 'escape.txt').exists())

    def test_verified_download_receipt_reuses_only_matching_bytes(self):
        with self.session() as session:
            with patch.object(self.transport, 'open_response', return_value=Response()):
                receipt = self.fetch(session)
            self.assertEqual(session.snapshot()['received_body_bytes'], 8)
            self.assertEqual(receipt['sha256'], hashlib.sha256(b'abcdefgh').hexdigest())
        with self.session() as session:
            with patch.object(self.transport, 'open_response', side_effect=AssertionError('no network')):
                self.assertEqual(self.fetch(session), receipt)
        (self.root / 'cache/data.zip').write_bytes(b'corrupt!')
        with self.session() as session, self.assertRaises(self.error):
            self.fetch(session)

    def test_oversize_hash_mismatch_and_http_failure_do_not_publish(self):
        for body, status in [(b'abcdefghX', 200), (b'wrong!!!', 200), (b'no', 503)]:
            with self.subTest(status=status, body=body):
                other = self.transport.AcquisitionSession(self.root / str(status) / body.hex(), {
                    'allow_hosts': ['zenodo.org'], 'max_received_body_bytes': 32,
                    'deadline_seconds': 120, 'max_attempts': 1})
                with other, patch.object(self.transport, 'open_response', return_value=Response(body, status=status)):
                    with self.assertRaises(self.error):
                        self.fetch(other)
                    self.assertFalse((other.root / 'data.zip').exists())
                    self.assertGreater(other.snapshot()['received_body_bytes'], 0)

    def test_interrupted_buffered_read_charges_reservation_across_resume(self):
        response = http.client.HTTPResponse(SimpleNamespace(makefile=lambda mode:
            io.BufferedReader(InterruptedBufferedBody(), buffer_size=8)))
        response.chunked = False; response.length = None
        self.addCleanup(response.close)
        with self.session(budget=8) as session:
            attempt = {'received_bytes': 0}
            with self.assertRaises(TimeoutError):
                session._read(response, 8, attempt)
            self.assertEqual(session.snapshot()['interrupted_body_bytes_upper_bound'], 8)
            self.assertEqual(attempt['received_bytes'], 0)
        with self.session(budget=8) as session:
            with patch.object(self.transport, 'open_response', side_effect=AssertionError('no network')):
                with self.assertRaises(self.error): self.fetch(session)

    def test_deadline_stops_reads_and_unapproved_requests_do_not_open_network(self):
        with self.session() as session:
            with patch.object(self.transport.time, 'monotonic', side_effect=[0, 0, 121, 121]):
                with patch.object(self.transport, 'open_response', return_value=Response()):
                    with self.assertRaises(self.error): self.fetch(session)
            self.assertFalse((session.root / 'data.zip').exists())
        with self.session() as session, patch.object(self.transport, 'open_response', side_effect=AssertionError('no network')):
            with self.assertRaises(self.error):
                session.fetch('https://unapproved.example/body', session.root / 'other.zip',
                              resource='other', max_bytes=8)

    def test_session_lock_and_stage_publication_are_exclusive(self):
        with self.session():
            with self.assertRaises(self.error):
                with self.session(): pass
        stage = self.root / 'stage'; stage.mkdir(); (stage / 'a.json').write_text('{}')
        output = self.root / 'complete'
        self.integrity.publish_stage(stage, output, {'a.json': self.integrity.sha256(stage / 'a.json')})
        self.assertEqual((output / 'a.json').read_text(), '{}')
        stage.mkdir(); (stage / 'a.json').write_text('{"changed":true}')
        with self.assertRaises((self.error, FileExistsError)):
            self.integrity.publish_stage(stage, output, {'a.json': self.integrity.sha256(stage / 'a.json')})

    def test_canonical_manifest_identity_ignores_line_endings_not_values(self):
        self.assertEqual(self.integrity.canonical_sha256(json.loads('{"a":1}\r\n')),
                         self.integrity.canonical_sha256(json.loads('{"a":1}\n')))
        self.assertNotEqual(self.integrity.canonical_sha256({'a': 1}),
                            self.integrity.canonical_sha256({'a': 2}))
        with self.assertRaises((self.error, ValueError)):
            self.integrity.canonical_sha256({'a': float('nan')})
