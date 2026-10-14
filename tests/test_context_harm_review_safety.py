"""Regressions for the independent review; entirely invented local inputs."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from sentinel.context_harm.contracts import FrozenStudy, HarmError, WorkerRecord
from sentinel.context_harm.source import default_settings
from context_harm_review_workers import URL, slow_response

HELPER = Path(__file__).with_name('context_harm_review_workers.py')


class AcquisitionDeadlineTests(unittest.TestCase):
    def test_owned_success_is_hash_checked_and_cached_without_launching_again(self):
        from sentinel.context_harm import transport
        from sentinel.context_harm.runtime import run_worker
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            limits = {'allow_hosts': ['zenodo.org'], 'max_received_body_bytes': 64,
                      'deadline_seconds': 3, 'max_attempts': 1}
            def launch(command, worker_limits, **options):
                return run_worker([sys.executable, str(HELPER), 'fast'], worker_limits, **options)
            arguments = {'resource': 'fixture', 'max_bytes': 32, 'expected_size': 32,
                         'expected_sha256': hashlib.sha256(b'x' * 32).hexdigest()}
            with transport.AcquisitionSession(root, limits) as session, \
                    patch('sentinel.context_harm.runtime.run_worker', side_effect=launch) as worker:
                receipt = session.fetch(URL, root / 'body.bin', **arguments)
                self.assertEqual(session.snapshot()['received_body_bytes'], 32)
                self.assertEqual((root / 'body.bin').read_bytes(), b'x' * 32)
                self.assertEqual(session.fetch(URL, root / 'body.bin', **arguments), receipt)
                worker.assert_called_once()
            with transport.AcquisitionSession(root, limits) as session, \
                    patch('sentinel.context_harm.runtime.run_worker', side_effect=AssertionError('cache launched a worker')):
                self.assertEqual(session.fetch(URL, root / 'body.bin', **arguments), receipt)

    def test_absolute_deadline_covers_progressing_body_headers_and_connection(self):
        from sentinel.context_harm import transport
        from sentinel.context_harm.runtime import run_worker
        import psutil

        for mode in ('body', 'headers', 'connect'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                measurements = []

                def launch(command, limits, **options):
                    result = run_worker([sys.executable, str(HELPER), mode], limits, **options)
                    measurements.append(result.measurements)
                    return result

                limits = {'allow_hosts': ['zenodo.org'], 'max_received_body_bytes': 64,
                          'deadline_seconds': 1, 'max_attempts': 1}
                with transport.AcquisitionSession(root, limits) as session:
                    started = time.monotonic()
                    with patch.object(transport, 'open_response', side_effect=lambda *args: slow_response(mode)), \
                            patch('sentinel.context_harm.runtime.run_worker', side_effect=launch):
                        with self.assertRaisesRegex(HarmError, 'source_deadline_exceeded'):
                            session.fetch(URL, root / 'body.bin', resource='fixture', max_bytes=32,
                                          expected_sha256=hashlib.sha256(b'x' * 32).hexdigest(), expected_size=32)
                    self.assertLess(time.monotonic() - started, 2.2, 'progress kept a network operation alive past its deadline')
                    state = session.snapshot()
                    self.assertEqual(state['inflight_bytes'], 0)
                    if mode == 'body':
                        self.assertGreater(state['interrupted_body_bytes_upper_bound'], 0)
                    self.assertFalse((root / 'body.bin').exists())
                    self.assertFalse(list(root.glob('.pending-fetch-*')))
                self.assertTrue(measurements, 'network acquisition did not use an owned process')
                for measured in measurements:
                    self.assertTrue(measured['cleanup_complete'])
                    self.assertFalse(psutil.pid_exists(measured['pid']))
                with transport.AcquisitionSession(root, limits):
                    pass


class SharedTrainingAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.marker, self.release = self.root / 'entered', self.root / 'release'
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        self.holder = subprocess.Popen([sys.executable, str(HELPER), 'hold-cpu', str(self.marker),
                                       str(self.release), str(self.root / 'holder-models')],
                                      env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.finish_holder)
        until = time.monotonic() + 10
        while not self.marker.exists() and self.holder.poll() is None and time.monotonic() < until:
            time.sleep(.02)
        self.assertTrue(self.marker.exists(), 'fixture did not enter the CPU fitting worker')

    def finish_holder(self):
        self.release.touch()
        if self.holder.poll() is None:
            self.holder.communicate(timeout=10)

    def test_cpu_neural_and_pilot_refuse_concurrent_process_before_worker_launch(self):
        from sentinel.context_harm import cpu, neural, protocol
        study = FrozenStudy(self.root / 'study', {})
        unavailable = WorkerRecord('unavailable', 'fixture_worker_reached', {}, {})
        settings = default_settings()
        with patch.object(protocol, 'assert_fitting_allowed'), patch.object(cpu, 'run_worker', return_value=unavailable) as worker:
            with self.assertRaisesRegex(HarmError, 'cpu_fitting_busy'):
                cpu.fit_cpu_candidates(study, self.root / 'different-cpu-output', settings)
            worker.assert_not_called()
        pilot = {'status': 'ready', 'may_fit_full_candidate': True, 'sources': {}, 'compatible_cohort': {}}
        with patch.object(protocol, 'assert_fitting_allowed'), patch.object(protocol, 'verify_study', return_value={}), \
                patch.object(neural, '_pilot_checked'), patch.object(neural, 'run_worker', return_value=unavailable) as worker:
            self.assertEqual(neural.fit_neural_candidates(study, pilot, Path(sys.executable), self.root / 'neural-models', settings), ())
            import json
            reason = json.loads((self.root / 'neural-models.neural-unavailable.json').read_text())['reason']
            self.assertEqual(reason, 'neural_fitting_busy')
            worker.assert_not_called()
        with patch.object(protocol, 'assert_fitting_allowed'), patch('sentinel.context_harm.neural_sources.verify_sources'), \
                patch.object(neural, 'run_worker', return_value=unavailable) as worker:
            value = neural.run_neural_pilot(study, Path(sys.executable), {}, self.root / 'pilot.json')
            self.assertEqual(value['reason'], 'neural_fitting_busy')
            worker.assert_not_called()
        self.finish_holder()
        with patch.object(protocol, 'assert_fitting_allowed'), patch.object(cpu, 'run_worker', return_value=unavailable) as worker:
            with self.assertRaisesRegex(HarmError, 'fixture_worker_reached'):
                cpu.fit_cpu_candidates(study, self.root / 'after-failure', settings)
            worker.assert_called_once()

    def test_abandoned_training_process_does_not_leave_permanent_admission_lock(self):
        from sentinel.context_harm import cpu, protocol
        self.holder.kill()
        self.holder.communicate(timeout=10)
        unavailable = WorkerRecord('unavailable', 'fixture_worker_reached', {}, {})
        with patch.object(protocol, 'assert_fitting_allowed'), patch.object(cpu, 'run_worker', return_value=unavailable) as worker:
            with self.assertRaisesRegex(HarmError, 'fixture_worker_reached'):
                cpu.fit_cpu_candidates(FrozenStudy(self.root / 'study', {}), self.root / 'after-crash', default_settings())
            worker.assert_called_once()


class NeuralRuntimeAttestationTests(unittest.TestCase):
    def test_final_runtime_drift_is_refused_before_reservation_or_test_access(self):
        from sentinel.context_harm import evaluation, neural
        from sentinel.context_harm.integrity import canonical_sha256, write_json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / 'artifact/manifest.json', {})
            metadata = {'protocol_manifest_sha256': canonical_sha256({}), 'implementation': {},
                        'branches': {}, 'preprocessing': {}, 'coverage': {'context': 'available'}, 'neural_settings': {}}
            candidate = SimpleNamespace(fit_record={'neural_python': sys.executable, 'runtime_probe': {}})
            bundle = {'metadata': metadata, 'selections': {'target_neural': SimpleNamespace(candidate=candidate)}}
            with patch.object(evaluation, 'verify_study', return_value={'case_hashes': {}}), \
                    patch.object(neural, 'run_worker', return_value=WorkerRecord('unavailable', 'neural_runtime_changed', {}, {})):
                with self.assertRaisesRegex(HarmError, 'neural_runtime_changed'):
                    evaluation._identity(FrozenStudy(root / 'study', {}), bundle, root / 'artifact', root / 'output')
            self.assertFalse((root / 'final-access.json').exists())

    def test_pilot_fit_and_score_reject_actual_runtime_drift_before_loading_text_or_models(self):
        from sentinel.context_harm import neural, protocol
        from sentinel.context_harm.integrity import canonical_sha256, sha256, write_json

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'study'
            write_json(path / 'manifest.json', {})
            binding = neural.runtime_identity_for_inventory(neural.expected_inventory(),
                        python_executable_sha256=sha256(Path(sys.executable)), base_executable_sha256=sha256(Path(sys._base_executable)),
                        cuda_version='12.8', device_name='software_fixture', device_total_bytes=4*1024**3, amp_supported=True)
            probe = {'runtime_binding': binding, 'runtime_sha256': canonical_sha256(binding),
                     'cuda_smoke': {key: True for key in ('forward', 'backward', 'optimizer')},
                     'peak_allocated_bytes': 100, 'peak_reserved_bytes': 100}
            record = {'runtime_probe': probe, 'runtime_sha256': probe['runtime_sha256']}
            write_json(root / 'candidate/fit-record.json', record)
            changed_python = root / 'different-python.exe'
            changed_python.write_bytes(b'not the probed interpreter')

            for drift in ('interpreter', 'base_interpreter', 'cuda', 'device_name', 'device_capacity', 'amp'):
                for operation in ('neural_pilot', 'neural_fit', 'neural_score'):
                    with self.subTest(drift=drift, operation=operation):
                        torch = SimpleNamespace(version=SimpleNamespace(cuda='12.7' if drift == 'cuda' else '12.8'),
                            cuda=SimpleNamespace(is_available=lambda: True, current_device=lambda: 0,
                                get_device_name=lambda _: 'different_device' if drift == 'device_name' else 'software_fixture',
                                get_device_properties=lambda _: SimpleNamespace(total_memory=5*1024**3 if drift == 'device_capacity' else 4*1024**3),
                                get_device_capability=lambda _: (6, 1) if drift == 'amp' else (8, 6)))
                        request = {'operation': operation, 'study_path': str(path), 'study_manifest_sha256': canonical_sha256({}),
                                   'sources': {}, 'probe': probe, 'pilot': {'probe': probe}, 'settings': default_settings(),
                                   'candidate_directory': str(root / 'candidate'), 'fit_record_sha256': canonical_sha256(record),
                                   'kind': 'target_neural', 'config_id': 'target_neural-lr2e-5', 'rows': []}
                        with patch.object(protocol, 'assert_fitting_allowed'), patch.object(neural, '_verified_sources', return_value={}), \
                                patch.object(neural, '_pilot_checked'), patch.object(neural, 'checked_candidate', return_value=record), \
                                patch.object(neural, '_runtime_inventory', return_value=(binding['inventory'], 'fixture')), \
                                patch.dict(sys.modules, {'torch': torch}), \
                                patch.object(neural, '_compatible_development', side_effect=AssertionError('text loaded before runtime attestation')), \
                                patch.object(neural, '_load_tokenizer', side_effect=AssertionError('tokenizer loaded before runtime attestation')), \
                                patch.object(sys, 'executable', str(changed_python) if drift == 'interpreter' else sys.executable), \
                                patch.object(sys, '_base_executable', str(changed_python) if drift == 'base_interpreter' else sys._base_executable):
                            with self.assertRaisesRegex(HarmError, 'neural_runtime_changed'):
                                neural.worker_operation(request)
