"""Real process and native ownership checks for bounded harm work."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from sentinel.context_harm.contracts import WorkerLimits


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def runtime(self):
        try:
            return importlib.import_module('sentinel.context_harm.runtime')
        except ModuleNotFoundError:
            self.fail('bounded harm runtime is missing')

    def child(self, action):
        path = self.root / ('child-' + str(len(list(self.root.glob('child-*.py')))) + '.py')
        path.write_text('from sentinel.context_harm.worker import await_ownership\nawait_ownership()\n' + action, encoding='utf-8')
        return [sys.executable, str(path)]

    def run_child(self, action, *, seconds=5, rss=512 * 1024**2, payload=None, cancel=None):
        return self.runtime().run_worker(self.child(action), WorkerLimits(seconds, rss, 4),
                                         input_payload=payload, cancel=cancel)

    def test_worker_receives_memory_only_payload_and_four_native_threads(self):
        record = self.run_child("import os,sys,json\npayload=sys.stdin.buffer.read()\nprint(json.dumps({'length':len(payload),'threads':[os.environ[k] for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')]}))\n", payload=b'private unsaved message')
        self.assertEqual(record.status, 'ok', record)
        self.assertEqual(record.output, {'length': 23, 'threads': ['4'] * 4})
        self.assertEqual(record.measurements['ownership'], 'windows_job_kill_on_close')
        self.assertLessEqual(record.measurements['rss_peak_bytes'], 512 * 1024**2)
        self.assertEqual(record.measurements['poll_seconds'], 0.1)
        self.assertEqual(list(self.root.glob('*.json')), [])
        self.assertNotIn('private unsaved', json.dumps(record.__dict__))

    def test_deadline_kills_real_worker(self):
        record = self.run_child('import time\ntime.sleep(20)\n', seconds=1)
        self.assertEqual(record.status, 'unavailable')
        self.assertEqual(record.reason, 'worker_deadline_exceeded')
        self.assertLess(record.measurements['wall_seconds'], 4)
        import psutil
        self.assertFalse(psutil.pid_exists(record.measurements['pid']))

    def test_cancelled_running_worker_releases_native_job(self):
        event = threading.Event()
        timer = threading.Timer(0.7, event.set)
        timer.start()
        self.addCleanup(timer.cancel)
        record = self.run_child('import time\ntime.sleep(20)\n', cancel=event)
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_cancelled'))
        import psutil
        self.assertFalse(psutil.pid_exists(record.measurements['pid']))

    def test_parent_exit_cannot_leave_a_sleeping_descendant_alive(self):
        marker = self.root / 'descendant.pid'
        script = "import subprocess,sys,json\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nPath(" + repr(str(marker)) + ").write_text(str(p.pid))\nprint(json.dumps({'done':True}))\n"
        record = self.run_child(script)
        self.assertTrue(marker.exists(), 'real descendant must have been launched')
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_descendants_survived'))
        import psutil
        self.assertFalse(psutil.pid_exists(int(marker.read_text())))
        self.assertTrue(record.measurements['cleanup_complete'])

    def test_deadline_kills_descendants_even_when_parent_sleeps(self):
        marker = self.root / 'descendant.pid'
        script = "import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nPath(" + repr(str(marker)) + ").write_text(str(p.pid))\ntime.sleep(20)\n"
        record = self.run_child(script, seconds=1)
        self.assertEqual(record.reason, 'worker_deadline_exceeded')
        self.assertTrue(marker.exists())
        import psutil
        self.assertFalse(psutil.pid_exists(int(marker.read_text())))

    def test_descendant_rss_is_part_of_the_memory_cap(self):
        marker = self.root / 'descendant.pid'
        script = "import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time;chunk=bytearray(90*1024**2);time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nPath(" + repr(str(marker)) + ").write_text(str(p.pid))\ntime.sleep(20)\n"
        record = self.run_child(script, rss=75 * 1024**2)
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_rss_limit_exceeded'))
        self.assertGreater(record.measurements['rss_peak_bytes'], 75 * 1024**2)
        self.assertGreaterEqual(record.measurements['process_count'], 2)
        import psutil
        self.assertFalse(psutil.pid_exists(int(marker.read_text())))

    def test_output_overflow_is_bounded_and_never_returned_as_private_text(self):
        record = self.run_child("import sys\nsys.stdout.write('PRIVATE_TARGET_'*9000)\nsys.stdout.flush()\n")
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_output_limit_exceeded'))
        self.assertEqual(record.output, {})
        self.assertLessEqual(record.measurements['stdout_retained_bytes'], 65536)
        self.assertNotIn('PRIVATE_TARGET_', json.dumps(record.__dict__))

    def test_failed_worker_stderr_is_not_exposed(self):
        record = self.run_child("import sys\nsys.stderr.write('raw private target, username and path')\nsys.exit(3)\n")
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_exit_failure'))
        self.assertEqual(record.output, {})
        self.assertNotIn('raw private', json.dumps(record.__dict__))

    def test_unowned_worker_rejects_before_private_file_read_or_ml_import(self):
        request = self.root / 'request.json'
        request.write_text('PRIVATE_TARGET_NOT_VALID_JSON', encoding='utf-8')
        child = subprocess.run([sys.executable, '-m', 'sentinel.context_harm.worker', '--request', str(request)],
                               input=b'bad-owner\n', capture_output=True, timeout=4)
        self.assertNotEqual(child.returncode, 0)
        self.assertTrue(child.stdout, 'unowned worker must emit a safe failure record')
        self.assertEqual(json.loads(child.stdout)['reason'], 'worker_ownership_unavailable')
        self.assertNotIn(b'PRIVATE_TARGET', child.stdout + child.stderr)

    def test_unsafe_limits_and_oversized_payload_fail_before_launch(self):
        runtime = self.runtime()
        for limits in (WorkerLimits(0, 100, 4), WorkerLimits(1, 8589934593, 4), WorkerLimits(1, 100, 5)):
            with self.subTest(limits=limits):
                record = runtime.run_worker([sys.executable, '-c', 'raise AssertionError()'], limits)
                self.assertEqual((record.status, record.reason), ('unavailable', 'worker_limits_invalid'))
                self.assertNotIn('pid', record.measurements)
        record = runtime.run_worker([sys.executable, '-c', 'raise AssertionError()'], WorkerLimits(1, 100, 4),
                                    input_payload=b'x' * (runtime.MAX_INPUT_BYTES + 1))
        self.assertEqual(record.reason, 'worker_input_oversized')
        self.assertNotIn('pid', record.measurements)


if __name__ == '__main__':
    unittest.main()


class OwnershipFailureTests(unittest.TestCase):
    setUp = RuntimeTests.setUp
    runtime = RuntimeTests.runtime
    child = RuntimeTests.child
    def test_native_assignment_failure_sends_no_payload_and_kills_unowned_child(self):
        from unittest.mock import patch
        runtime = self.runtime()
        command = self.child("raise AssertionError('private request must not execute')\n")
        with patch.object(runtime._WindowsJob, 'assign', side_effect=OSError('cannot own child')):
            record = runtime.run_worker(command, WorkerLimits(5, 512*1024**2, 4), input_payload=b'PRIVATE_UNSAVED')
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_ownership_unavailable'))
        import psutil
        self.assertFalse(psutil.pid_exists(record.measurements['pid']))
        self.assertTrue(record.measurements['cleanup_complete'])

    def test_failed_initial_rss_measurement_never_releases_ownership_handshake(self):
        import psutil
        from unittest.mock import patch
        marker = self.root / 'executed'
        command = self.child('from pathlib import Path\nPath(' + repr(str(marker)) + ").write_text('PRIVATE_UNSAVED')\n")
        with patch.object(psutil.Process, 'memory_info', side_effect=psutil.AccessDenied()):
            record = self.runtime().run_worker(command, WorkerLimits(5, 512*1024**2, 4), input_payload=b'PRIVATE_UNSAVED')
        self.assertEqual((record.status, record.reason), ('unavailable', 'worker_monitoring_unavailable'))
        self.assertFalse(marker.exists())
        self.assertTrue(record.measurements['cleanup_complete'])


class SafeWorkerFailureTests(unittest.TestCase):
    def test_owned_worker_preserves_controlled_failure_code_without_payload_text(self):
        from sentinel.context_harm.runtime import run_worker
        payload=b'{"operation":"invalid_operation","private":"PRIVATE_UNSAVED_TEXT"}'
        record=run_worker([sys.executable,'-m','sentinel.context_harm.worker','--request-stdin'],WorkerLimits(5,512*1024**2,4),input_payload=payload)
        self.assertEqual((record.status,record.reason),('unavailable','worker_operation_invalid'))
        self.assertEqual(record.output,{})
        self.assertNotIn('PRIVATE_UNSAVED_TEXT',json.dumps(record.__dict__))
