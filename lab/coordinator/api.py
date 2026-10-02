"""Coordinator HTTP API. Workers authenticate with the bearer token."""
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def make_handler(db, store, token, grace, lease_seconds, drain_margin_seconds=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            self._route('GET')

        def do_POST(self):
            self._route('POST')

        def _route(self, method):
            try:
                self._auth()
                path = urlparse(self.path).path.strip('/').split('/')
                if method == 'GET' and path == ['api', 'health']:
                    return self._send({'ok': True})
                if method == 'GET' and path == ['api', 'jobs']:
                    return self._send({'jobs': db.jobs()})
                if method == 'GET' and path == ['api', 'workers']:
                    return self._send({'workers': db.workers()})
                if method == 'GET' and len(path) == 3 and path[:2] == ['api', 'jobs']:
                    return self._send(db.job(path[2]))
                body = self._body() if method == 'POST' else {}
                if method == 'POST' and path == ['api', 'claim']:
                    claimed = db.claim(
                        body['worker_id'], body.get('backend', 'local'), body.get('host', ''),
                        int(lease_seconds), grace, expected_commit=body.get('expected_commit') or None,
                        drain_margin_seconds=int(drain_margin_seconds),
                    )
                    return self._send({'claim': claimed})
                if method == 'POST' and path == ['api', 'heartbeat']:
                    return self._send(db.heartbeat(body['lease_id'], body['worker_id'], grace))
                if method == 'POST' and path == ['api', 'release']:
                    db.release(body['lease_id'], body['worker_id'], body['reason'])
                    return self._send({'ok': True})
                if method == 'POST' and path == ['api', 'results']:
                    result = db.save_result(
                        body['lease_id'], body['worker_id'], body['object_key'], body['sha256'],
                        body['size'], body.get('metadata') or {}, store,
                    )
                    return self._send(result)
                if method == 'POST' and path == ['api', 'checkpoints']:
                    result = db.stage_and_verify(
                        body['lease_id'], body['worker_id'], body['seq'], body['sha256'],
                        body['size'], body['object_key'], store,
                    )
                    return self._send(result)
                if method == 'POST' and len(path) == 4 and path[:2] == ['api', 'jobs'] and path[3] == 'cancel':
                    return self._send(db.cancel(path[2]))
                self._send({'error': 'not found'}, 404)
            except APIError as exc:
                self._send({'error': str(exc)}, exc.status)
            except PermissionError as exc:
                self._send({'error': str(exc)}, 403)
            except KeyError as exc:
                self._send({'error': f'unknown id {exc}'}, 404)
            except (ValueError, TypeError) as exc:
                self._send({'error': str(exc)}, 400)
            except Exception:
                self._send({'error': 'internal coordinator error'}, 500)

        def _auth(self):
            header = self.headers.get('Authorization', '')
            presented = header[7:] if header.startswith('Bearer ') else ''
            if not token or not hmac.compare_digest(presented, token):
                raise APIError(401, 'unauthorized')

        def _body(self):
            length = int(self.headers.get('Content-Length', '0') or 0)
            if length > 1_000_000:
                raise APIError(400, 'request too large')
            raw = self.rfile.read(length) if length else b'{}'
            data = json.loads(raw.decode() or '{}')
            if not isinstance(data, dict):
                raise APIError(400, 'JSON object required')
            return data

        def _send(self, payload, status=200):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def serve_http(db, store, token, grace, lease_seconds, hosts, port, drain_margin_seconds=0):
    handler = make_handler(db, store, token, grace, lease_seconds, drain_margin_seconds)
    servers = []
    for host in hosts:
        httpd = ThreadingHTTPServer((host, port), handler)
        servers.append(httpd)
    return servers
