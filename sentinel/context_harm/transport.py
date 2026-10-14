"""Official-source reads with durable byte reservations and request deadlines."""
import hashlib
import http.client
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.ranges import approved_url, cache_lock, open_response
from .contracts import HarmError, WorkerLimits
from .integrity import canonical_bytes, canonical_sha256, read_json, safe_path, sha256, write_json


class AcquisitionSession:
    def __init__(self, root: Path, limits: dict):
        self.root = Path(root).resolve()
        self.limits = dict(limits)
        self.journal = self.root / 'journal.json'
        self.active = False
        self.deadline = None

    def __enter__(self):
        self.lock = cache_lock(self.root)
        try:
            self.lock.__enter__()
        except DatasetError as error:
            raise HarmError('source_session_busy') from error
        self.active = True
        try:
            self._restore_journal()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _restore_journal(self):
        """Called only while the supervisor owns the session lock and worker is stopped."""
        identity = canonical_sha256(self.limits)
        if self.journal.exists():
            self.state = read_json(self.journal)
            if self.state.get('schema') != 'harm-acquisition-1' or self.state.get('limits_sha256') != identity:
                raise HarmError('source_journal_identity_mismatch')
            keys = ('received_body_bytes', 'interrupted_body_bytes_upper_bound', 'inflight_bytes')
            if any(type(self.state.get(key)) is not int or self.state[key] < 0 for key in keys):
                raise HarmError('source_budget_invalid')
            if sum(self.state[key] for key in keys) > self.limits['max_received_body_bytes']:
                raise HarmError('source_budget_invalid')
            if not isinstance(self.state.get('attempts'), list) or not isinstance(self.state.get('receipts'), dict):
                raise HarmError('source_journal_invalid')
        else:
            self.state = {'schema': 'harm-acquisition-1', 'limits_sha256': identity,
                          'received_body_bytes': 0, 'interrupted_body_bytes_upper_bound': 0,
                          'inflight_bytes': 0, 'attempts': [], 'receipts': {}}
        self.state['interrupted_body_bytes_upper_bound'] += self.state['inflight_bytes']
        self.state['inflight_bytes'] = 0
        for attempt in self.state['attempts']:
            if attempt.get('status') == 'started':
                attempt.update(status='interrupted', reason='source_worker_interrupted')
        self._save()
        for pending in self.root.glob('.pending-fetch-*'):
            if pending.is_file() and pending.parent == self.root:
                pending.unlink()

    def __exit__(self, *args):
        if self.active:
            self.active = False
            self.lock.__exit__(*args)

    def snapshot(self):
        import json
        return json.loads(json.dumps(self.state))

    def _save(self):
        write_json(self.journal, self.state)

    def _remaining(self):
        return self.limits['max_received_body_bytes'] - sum(self.state[key] for key in
            ('received_body_bytes', 'interrupted_body_bytes_upper_bound', 'inflight_bytes'))

    def _time_left(self):
        if self.deadline is None:
            return self.limits['deadline_seconds']
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise HarmError('source_deadline_exceeded')
        return remaining

    def _read(self, response, amount, attempt):
        self._time_left()
        if type(amount) is not int or not 0 < amount <= self._remaining():
            raise HarmError('source_body_budget_exceeded')
        self.state['inflight_bytes'] = amount
        self._save()
        try:
            chunk = response.read(amount)
        except http.client.IncompleteRead as error:
            self._credit(error.partial, amount, attempt)
            raise
        except BaseException:
            self.state['interrupted_body_bytes_upper_bound'] += amount
            self.state['inflight_bytes'] = 0
            self._save()
            raise
        self._credit(chunk, amount, attempt)
        self._time_left()
        return chunk

    def _credit(self, chunk, amount, attempt):
        if not isinstance(chunk, bytes) or len(chunk) > amount:
            self.state['interrupted_body_bytes_upper_bound'] += amount
            self.state['inflight_bytes'] = 0
            self._save()
            raise HarmError('source_read_contract_invalid')
        self.state['inflight_bytes'] = 0
        self.state['received_body_bytes'] += len(chunk)
        attempt['received_bytes'] += len(chunk)
        self._save()

    def _prepare_fetch(self, url, target, resource, max_bytes, expected_sha256, expected_size):
        if not self.active:
            raise HarmError('source_session_not_owned')
        try:
            approved_url(url, self.limits['allow_hosts'])
        except DatasetError as error:
            raise HarmError('unapproved_source_endpoint') from error
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', resource) or type(max_bytes) is not int or max_bytes <= 0:
            raise HarmError('source_resource_invalid')
        target = Path(target).resolve()
        if not target.is_relative_to(self.root):
            raise HarmError('source_target_outside_session')
        relative = target.relative_to(self.root).as_posix()
        safe_path(self.root, relative)
        identity = {'url_sha256': hashlib.sha256(url.encode()).hexdigest(), 'path': relative,
                    'max_bytes': max_bytes, 'expected_sha256': expected_sha256, 'expected_size': expected_size}
        old = self.state['receipts'].get(resource)
        if old is not None:
            if any(old.get(key) != value for key, value in identity.items()):
                raise HarmError('source_receipt_identity_mismatch')
            if not target.is_file() or target.stat().st_size != old['size'] or sha256(target) != old['sha256']:
                raise HarmError('source_verified_cache_corrupt')
            return target, identity, old
        attempts = [item for item in self.state['attempts'] if item['resource'] == resource]
        if any(item['identity'] != identity for item in attempts):
            raise HarmError('source_attempt_identity_mismatch')
        if target.exists():
            raise HarmError('source_unregistered_cache')
        return target, identity, None

    def fetch(self, url, target, *, resource, max_bytes, expected_sha256=None, expected_size=None):
        """Own the entire connection/header/body operation, including blocking DNS.

        Socket timeouts bound inactivity only. The native worker deadline bounds
        absolute elapsed time and closes every socket even during slow progress.
        The supervisor retains the session lock while the worker writes its journal.
        """
        import sys
        from .runtime import run_worker
        arguments = (url, target, resource, max_bytes, expected_sha256, expected_size)
        target, _, cached = self._prepare_fetch(*arguments)
        if cached is not None:
            return cached
        if self._remaining() <= 0:
            raise HarmError('source_body_budget_exceeded')
        payload = {'operation': 'source_fetch', 'root': str(self.root), 'limits': self.limits,
                   'url': url, 'target': str(target), 'resource': resource, 'max_bytes': max_bytes,
                   'expected_sha256': expected_sha256, 'expected_size': expected_size}
        result = run_worker([sys.executable, '-m', 'sentinel.context_harm.worker', '--request-stdin'],
                            WorkerLimits(self.limits['deadline_seconds'], 512 * 1024**2, 1),
                            input_payload=canonical_bytes(payload))
        # run_worker kills and joins the whole tree before returning. Any read
        # interrupted before crediting its body retains the full byte reservation.
        self._restore_journal()
        self.state.setdefault('worker_runs', []).append({'resource': resource, 'status': result.status,
                                                       'reason': result.reason, 'measurements': result.measurements})
        self._save()
        if result.status != 'ok':
            reason = 'source_deadline_exceeded' if result.reason == 'worker_deadline_exceeded' else result.reason
            raise HarmError(reason or 'source_transport_unavailable')
        _, _, cached = self._prepare_fetch(*arguments)
        if cached is None or result.output.get('receipt') != cached:
            raise HarmError('source_worker_receipt_invalid')
        return cached

    def _fetch_owned(self, url, target, *, resource, max_bytes, expected_sha256=None, expected_size=None):
        """Network core: invoked inside the owned worker, never by application callers."""
        target, identity, cached = self._prepare_fetch(url, target, resource, max_bytes, expected_sha256, expected_size)
        if cached is not None:
            return cached
        attempts = [item for item in self.state['attempts'] if item['resource'] == resource]
        target.parent.mkdir(parents=True, exist_ok=True)
        for number in range(len(attempts) + 1, self.limits.get('max_attempts', 3) + 1):
            if self._remaining() <= 0:
                raise HarmError('source_body_budget_exceeded')
            attempt = {'resource': resource, 'identity': identity, 'attempt': number,
                       'received_bytes': 0, 'status': 'started'}
            self.state['attempts'].append(attempt)
            self._save()
            pending = self.root / ('.pending-fetch-' + uuid4().hex)
            response = None
            self.deadline = time.monotonic() + self.limits['deadline_seconds']
            try:
                request = urllib.request.Request(url, headers={
                    'Accept-Encoding': 'identity', 'User-Agent': 'Sentinel-Harm-Research/1'})
                try:
                    response = open_response(request, self.limits['allow_hosts'], min(15, self._time_left()))
                except urllib.error.HTTPError as error:
                    response = error
                approved_url(response.geturl(), self.limits['allow_hosts'])
                digest = hashlib.sha256(); size = 0
                with pending.open('xb') as stream:
                    while True:
                        remaining = self._remaining()
                        if remaining <= 0:
                            if response.headers.get('Content-Length') == str(size):
                                break
                            raise HarmError('source_body_budget_exceeded')
                        chunk = self._read(response, min(65536, max_bytes - size + 1, remaining), attempt)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise HarmError('source_body_oversized')
                        stream.write(chunk); digest.update(chunk)
                    stream.flush(); os.fsync(stream.fileno())
                if response.status != 200:
                    raise HarmError('source_http_unavailable')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise HarmError('source_encoded_body')
                length = response.headers.get('Content-Length')
                if length is not None and length != str(size):
                    raise HarmError('source_length_mismatch')
                actual = digest.hexdigest()
                if (expected_size is not None and size != expected_size) or (expected_sha256 is not None and actual != expected_sha256):
                    raise HarmError('source_pin_mismatch')
                receipt = {**identity, 'resource': resource, 'size': size, 'sha256': actual, 'complete': True}
                os.link(pending, target)
                self.state['receipts'][resource] = receipt
                attempt['status'] = 'verified'; self._save()
                return receipt
            except DatasetError as error:
                attempt['status'] = 'rejected'; attempt['reason'] = 'unapproved_source_endpoint'; self._save()
                raise HarmError('unapproved_source_endpoint') from error
            except HarmError as error:
                attempt['status'] = 'rejected'; attempt['reason'] = error.reason; self._save()
                raise
            except (OSError, urllib.error.URLError, http.client.IncompleteRead) as error:
                attempt['status'] = 'interrupted'; attempt['reason'] = type(error).__name__; self._save()
                if number >= self.limits.get('max_attempts', 3):
                    raise HarmError('source_transport_unavailable') from None
            finally:
                self.deadline = None
                if response is not None:
                    response.close()
                pending.unlink(missing_ok=True)
        raise HarmError('source_attempt_limit_exhausted')


def worker_fetch(request):
    session = AcquisitionSession(Path(request['root']), request['limits'])
    # The calling supervisor holds this root's lock throughout run_worker.
    # Child ownership was established before dispatch; it must not reacquire it.
    session.active = True
    session._restore_journal()
    receipt = session._fetch_owned(request['url'], request['target'], resource=request['resource'],
                                  max_bytes=request['max_bytes'], expected_sha256=request['expected_sha256'],
                                  expected_size=request['expected_size'])
    return {'receipt': receipt}
