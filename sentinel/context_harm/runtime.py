"""Supervised Windows workers with native process-tree ownership.

The named Job Object uses KILL_ON_JOB_CLOSE without breakaway. Process IDs are
queried from that job, so an orphaned descendant remains visible after its
parent exits. RSS is sampled separately: Windows job memory limits measure
committed virtual memory, which is a different quantity.
"""
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from ctypes import wintypes

from .contracts import WorkerLimits, WorkerRecord

MAX_INPUT_BYTES = 32 * 1024**2
MAX_OUTPUT_BYTES = 64 * 1024
MAX_RSS_BYTES = 8 * 1024**3
POLL_SECONDS = 0.1
NATIVE_THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                           'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')


class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                ('SchedulingClass', wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount',
               'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


def _kernel():
    if os.name != 'nt':
        raise OSError('native Windows ownership is required')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        'OpenJobObjectW': ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        'QueryInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        'IsProcessInJob': ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        'GetCurrentProcess': ([], wintypes.HANDLE),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


class _WindowsJob:
    def __init__(self, name):
        self.kernel = _kernel()
        self.handle = self.kernel.CreateJobObjectW(None, name)
        if not self.handle:
            raise OSError('job creation failed')
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError('job kill-on-close setup failed')

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError('job assignment failed')

    def members(self):
        capacity = 64
        while capacity <= 65536:
            class ProcessList(ctypes.Structure):
                _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD),
                            ('pids', ctypes.c_size_t * capacity)]
            result = ProcessList()
            success = self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(result),
                                                            ctypes.sizeof(result), None)
            if success and result.count == result.assigned and result.count <= capacity:
                return tuple(int(result.pids[i]) for i in range(result.count))
            if not success and ctypes.get_last_error() not in (122, 234):
                raise OSError('job membership query failed')
            capacity *= 2
        raise OSError('job process capacity exceeded')

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise OSError('job close failed')


def ownership_established(name: str) -> bool:
    """Verify exact supervisor job membership, then release the observer handle."""
    if not isinstance(name, str) or not re.fullmatch(r'SentinelHarm-[a-f0-9]{32}', name):
        return False
    kernel = _kernel()
    handle = kernel.OpenJobObjectW(0x0004, False, name)  # JOB_OBJECT_QUERY
    if not handle:
        return False
    try:
        owned = wintypes.BOOL()
        limits = _ExtendedLimits()
        return bool(kernel.IsProcessInJob(kernel.GetCurrentProcess(), handle, ctypes.byref(owned))
                    and owned.value and kernel.QueryInformationJobObject(handle, 9, ctypes.byref(limits),
                    ctypes.sizeof(limits), None) and limits.BasicLimitInformation.LimitFlags & 0x2000)
    finally:
        kernel.CloseHandle(handle)


class _BoundedPipe:
    def __init__(self, stream):
        self.stream, self.retained, self.received = stream, bytearray(), 0
        self.overflow, self.failed = False, False
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self):
        try:
            while True:
                chunk = self.stream.read(8192)
                if not chunk:
                    return
                self.received += len(chunk)
                remaining = MAX_OUTPUT_BYTES - len(self.retained)
                self.retained.extend(chunk[:max(0, remaining)])
                if self.received > MAX_OUTPUT_BYTES:
                    self.overflow = True
        except (OSError, ValueError):
            self.failed = True


def _valid_limits(limits):
    return (isinstance(limits, WorkerLimits) and type(limits.deadline_seconds) is int
            and 0 < limits.deadline_seconds <= 1800 and type(limits.rss_bytes) is int
            and 0 < limits.rss_bytes <= MAX_RSS_BYTES and type(limits.native_threads) is int
            and 1 <= limits.native_threads <= 4)


def _unavailable(reason):
    return WorkerRecord('unavailable', reason, {}, {})


def run_worker(command: list[str], limits: WorkerLimits, *, cancel: threading.Event | None = None,
               input_payload: bytes | None = None) -> WorkerRecord:
    """Launch one owned worker; only bounded aggregate measurements are retained."""
    if not _valid_limits(limits):
        return _unavailable('worker_limits_invalid')
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x or '\x00' in x for x in command):
        return _unavailable('worker_command_invalid')
    if input_payload is not None and not isinstance(input_payload, bytes):
        return _unavailable('worker_input_invalid')
    if input_payload is not None and len(input_payload) > MAX_INPUT_BYTES:
        return _unavailable('worker_input_oversized')
    if cancel is not None and cancel.is_set():
        return _unavailable('worker_cancelled')
    try:
        import psutil
        job_name, token = 'SentinelHarm-' + secrets.token_hex(16), secrets.token_hex(32)
        job = _WindowsJob(job_name)
    except Exception:
        return _unavailable('worker_ownership_unavailable')
    started, peak, process, reason = time.perf_counter(), 0, None, None
    known, outputs, writer = {}, [], None
    cleanup_complete = True
    assigned = False
    output = {}
    measurement_failed = False
    try:
        environment = dict(os.environ)
        for key in NATIVE_THREAD_VARIABLES:
            environment[key] = str(limits.native_threads)
        environment['SENTINEL_HARM_OWNER_TOKEN'] = token
        environment['SENTINEL_HARM_JOB_NAME'] = job_name
        environment['SENTINEL_HARM_NATIVE_THREADS'] = str(limits.native_threads)
        repository = str(Path(__file__).resolve().parents[2])
        environment['PYTHONPATH'] = repository + (os.pathsep + environment['PYTHONPATH'] if environment.get('PYTHONPATH') else '')
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=environment, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        job.assign(process)
        assigned = True
        outputs = [_BoundedPipe(process.stdout), _BoundedPipe(process.stderr)]
        for pipe in outputs:
            pipe.thread.start()

        def sample():
            nonlocal peak
            total = 0
            for pid in job.members():
                try:
                    member = psutil.Process(pid)
                    identity = (pid, member.create_time())
                    known[identity] = member
                    total += member.memory_info().rss
                except psutil.NoSuchProcess:
                    continue
            peak = max(peak, total)
            return total

        sample()  # fail before sending ownership or any payload if monitoring is unavailable
        def send_input():
            try:
                process.stdin.write((token + '\n').encode('ascii'))
                if input_payload is not None:
                    process.stdin.write(input_payload)
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        writer = threading.Thread(target=send_input, daemon=True)
        writer.start()
        while True:
            sample()
            if peak > limits.rss_bytes:
                reason = 'worker_rss_limit_exceeded'
                break
            if cancel is not None and cancel.is_set():
                reason = 'worker_cancelled'
                break
            if time.perf_counter() - started >= limits.deadline_seconds:
                reason = 'worker_deadline_exceeded'
                break
            if any(pipe.overflow for pipe in outputs):
                reason = 'worker_output_limit_exceeded'
                break
            if process.poll() is not None:
                members = job.members()
                descendants = []
                for pid in members:
                    if pid != process.pid:
                        try:
                            descendants.append(psutil.Process(pid))
                        except psutil.NoSuchProcess:
                            pass
                # Windows venv redirectors can finish before the kernel removes
                # their already exiting interpreter from the native job list.
                _, alive = psutil.wait_procs(descendants, timeout=POLL_SECONDS)
                if alive:
                    reason = 'worker_descendants_survived'
                elif process.returncode != 0:
                    reason = 'worker_exit_failure'
                break
            time.sleep(POLL_SECONDS)
    except (psutil.Error, OSError):
        reason = 'worker_monitoring_unavailable' if assigned else 'worker_ownership_unavailable'
        measurement_failed = True
    except Exception:
        reason = 'worker_ownership_unavailable'
    finally:
        try:
            if process is not None:
                for pid in job.members():
                    try:
                        member = psutil.Process(pid)
                        known[(pid, member.create_time())] = member
                    except psutil.NoSuchProcess:
                        pass
            job.close()  # also kills descendants when the direct parent already exited
            if process is not None and not assigned and process.poll() is None:
                process.kill()  # failed assignment never transferred native ownership
        except (OSError, psutil.Error):
            cleanup_complete = False
        if process is not None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
                cleanup_complete = False
            _, alive = psutil.wait_procs(list(known.values()), timeout=3)
            cleanup_complete = cleanup_complete and not alive
            if writer is not None:
                writer.join(timeout=1)
            for pipe in outputs:
                pipe.thread.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
    if not cleanup_complete:
        reason = 'worker_cleanup_failed'
    if outputs and any(pipe.overflow for pipe in outputs):
        reason = 'worker_output_limit_exceeded'
    if reason == 'worker_exit_failure' and outputs:
        try:
            failure = json.loads(bytes(outputs[0].retained))
            safe_reason = failure.get('reason') if isinstance(failure, dict) else None
            if (isinstance(failure, dict) and set(failure) == {'status', 'reason'}
                    and failure['status'] == 'unavailable' and isinstance(safe_reason, str)
                    and re.fullmatch(r'(?:worker|cpu|neural|cuda|harm|fitting|protected)_[a-z0-9_]{1,88}', safe_reason)):
                reason = safe_reason
        except (ValueError, UnicodeError):
            pass
    if reason is None:
        try:
            value = json.loads(bytes(outputs[0].retained), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict) or any(pipe.failed or pipe.thread.is_alive() for pipe in outputs):
                raise ValueError()
            output = value
        except (ValueError, UnicodeError):
            reason = 'worker_output_invalid'
    measurements = {'wall_seconds': time.perf_counter() - started, 'rss_peak_bytes': int(peak),
                    'rss_limit_bytes': limits.rss_bytes, 'deadline_seconds': limits.deadline_seconds,
                    'native_threads': limits.native_threads, 'poll_seconds': POLL_SECONDS,
                    'ownership': 'windows_job_kill_on_close', 'process_count': len(known),
                    'cleanup_complete': cleanup_complete, 'monitoring_complete': not measurement_failed,
                    'stdout_retained_bytes': len(outputs[0].retained) if outputs else 0,
                    'stderr_retained_bytes': len(outputs[1].retained) if outputs else 0,
                    'stdout_received_bytes': outputs[0].received if outputs else 0,
                    'stderr_received_bytes': outputs[1].received if outputs else 0}
    if process is not None:
        measurements.update(pid=process.pid, exit_code=process.returncode)
    return WorkerRecord('unavailable' if reason else 'ok', reason, measurements, {} if reason else output)

