"""Process and real HTTP stream fixtures; no remote requests or model fitting."""
import http.client
import socket
import sys
import threading
import time
from pathlib import Path

URL = 'https://zenodo.org/review-fixture'


def slow_response(mode):
    if mode == 'connect':
        time.sleep(4)
    reader, writer = socket.socketpair()
    reader.settimeout(.3)
    body = b'x' * 32

    def produce():
        try:
            header = b'HTTP/1.1 200 OK\r\nContent-Length: 32\r\n\r\n'
            if mode == 'fast':
                writer.sendall(header + body)
            elif mode == 'headers':
                for byte in header:
                    writer.sendall(bytes([byte]))
                    time.sleep(.1)
                writer.sendall(body)
            else:
                writer.sendall(header)
                for byte in body:
                    writer.sendall(bytes([byte]))
                    time.sleep(.12)
        except OSError:
            pass
        finally:
            writer.close()

    threading.Thread(target=produce, daemon=True).start()
    response = http.client.HTTPResponse(reader)
    response.begin()
    reader.close()
    response.geturl = lambda: URL
    return response


def hold_cpu(marker, release, output):
    from unittest.mock import patch
    from sentinel.context_harm import cpu, protocol
    from sentinel.context_harm.contracts import FrozenStudy, HarmError, WorkerRecord
    from sentinel.context_harm.source import default_settings

    def pause(*args, **kwargs):
        Path(marker).write_text('entered', encoding='ascii')
        until = time.monotonic() + 30
        while not Path(release).exists() and time.monotonic() < until:
            time.sleep(.02)
        return WorkerRecord('unavailable', 'fixture_fit_failure', {}, {})

    with patch.object(protocol, 'assert_fitting_allowed'), patch.object(cpu, 'run_worker', side_effect=pause):
        try:
            cpu.fit_cpu_candidates(FrozenStudy(Path(output).parent / 'study', {}), Path(output), default_settings())
        except HarmError as error:
            if error.reason != 'fixture_fit_failure':
                raise


if __name__ == '__main__':
    if sys.argv[1] == 'hold-cpu':
        hold_cpu(*sys.argv[2:])
    else:
        from sentinel.context_harm import transport, worker
        transport.open_response = lambda *args: slow_response(sys.argv[1])
        raise SystemExit(worker.main(['--request-stdin']))
