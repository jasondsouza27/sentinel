"""Private worker entry point; ownership precedes request reads and ML imports."""
import argparse
import hmac
import json
import os
from pathlib import Path
import re
import sys

from .contracts import HarmError
from .integrity import canonical_bytes, read_json


def await_ownership() -> None:
    from .runtime import NATIVE_THREAD_VARIABLES, ownership_established
    expected = os.environ.get('SENTINEL_HARM_OWNER_TOKEN', '')
    observed = sys.stdin.buffer.readline(130).rstrip(b'\r\n')
    native_threads = os.environ.get('SENTINEL_HARM_NATIVE_THREADS', '')
    if (not re.fullmatch(r'[a-f0-9]{64}', expected) or not hmac.compare_digest(observed, expected.encode('ascii'))
            or native_threads not in {'1', '2', '3', '4'}
            or any(os.environ.get(key) != native_threads for key in NATIVE_THREAD_VARIABLES)):
        raise HarmError('worker_ownership_unavailable')
    try:
        if not ownership_established(os.environ.get('SENTINEL_HARM_JOB_NAME', '')):
            raise HarmError('worker_ownership_unavailable')
    except OSError:
        raise HarmError('worker_ownership_unavailable') from None


def _dispatch(request: dict) -> dict:
    operation = request.get('operation')
    if operation in {'cpu_fit', 'cpu_score'}:
        from .cpu import worker_operation
        return worker_operation(request)
    if operation in {'neural_probe', 'neural_pilot', 'neural_fit', 'neural_score'}:
        from .neural import worker_operation
        return worker_operation(request)
    if operation == 'harm_infer':
        from .service import worker_infer
        return worker_infer(request)
    raise HarmError('worker_operation_invalid')


def main(argv=None) -> int:
    try:
        await_ownership()
        parser = argparse.ArgumentParser(add_help=False)
        inputs = parser.add_mutually_exclusive_group(required=True)
        inputs.add_argument('--request', type=Path)
        inputs.add_argument('--request-stdin', action='store_true')
        options = parser.parse_args(argv)
        if options.request_stdin:
            from .runtime import MAX_INPUT_BYTES
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise HarmError('worker_input_oversized')
            request = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(request, dict):
                raise HarmError('worker_request_invalid')
        else:
            request = read_json(options.request)
        result = _dispatch(request)
        if not isinstance(result, dict):
            raise HarmError('worker_result_invalid')
        sys.stdout.buffer.write(canonical_bytes(result) + b'\n')
        return 0
    except Exception as error:
        reason = error.reason if isinstance(error, HarmError) and re.fullmatch(r'[a-z][a-z0-9_]{0,95}', error.reason) else 'worker_operation_failed'
        sys.stdout.buffer.write(canonical_bytes({'status': 'unavailable', 'reason': reason}) + b'\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
