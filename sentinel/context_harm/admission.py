"""One nonblocking training reservation across model families and processes."""
import ctypes
from ctypes import wintypes
import os
import threading

from .contracts import HarmError

_THREAD_ADMISSION = threading.Lock()
_MUTEX_NAME = 'Local\\SentinelHarmTraining-v1'


class TrainingAdmission:
    """Supervisor lease; children inherit job ownership, never reacquire the lease.

    A Windows mutex releases on owner death. A shared local lock also prevents
    Windows' recursive mutex semantics from admitting two fits on one thread.
    Its name is independent of the study, output, interpreter and worktree.
    """
    def __init__(self):
        self.handle = None
        self.kernel = None

    def acquire(self, blocking=False):
        if blocking:
            raise HarmError('harm_training_admission_must_not_wait')
        if not _THREAD_ADMISSION.acquire(blocking=False):
            return False
        handle, kernel = None, None
        try:
            if os.name != 'nt':
                raise OSError('Windows training ownership is required')
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            for name, arguments, result in (
                ('CreateMutexW', [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
                ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
                ('ReleaseMutex', [wintypes.HANDLE], wintypes.BOOL),
                ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
            ):
                function = getattr(kernel, name)
                function.argtypes, function.restype = arguments, result
            handle = kernel.CreateMutexW(None, False, _MUTEX_NAME)
            if not handle:
                raise OSError('training mutex creation failed')
            result = kernel.WaitForSingleObject(handle, 0)
            if result in (0, 0x80):  # WAIT_OBJECT_0 or recovered WAIT_ABANDONED
                self.handle, self.kernel = handle, kernel
                return True
            if result != 0x102:  # WAIT_TIMEOUT: another process holds the lease
                raise OSError('training mutex observation failed')
            return False
        except OSError:
            raise HarmError('harm_training_admission_unavailable') from None
        finally:
            if self.handle is None:
                if handle:
                    kernel.CloseHandle(handle)
                _THREAD_ADMISSION.release()

    def release(self):
        if self.handle is None:
            raise HarmError('harm_training_admission_not_owned')
        handle, kernel = self.handle, self.kernel
        self.handle, self.kernel = None, None
        try:
            if not kernel.ReleaseMutex(handle):
                raise HarmError('harm_training_admission_release_failed')
        finally:
            kernel.CloseHandle(handle)
            _THREAD_ADMISSION.release()
