"""OpenRouter calls. One key covers Jev and Luna."""
import json
import urllib.request


class PlannerError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, cfg, post=None):
        self.cfg = cfg
        self._post = post or _post

    def decisions(self, state, questions):
        self._require_key()
        return self._post(self.cfg.decisions_url, {
            'model': self.cfg.jev_model,
            'state': state,
            'questions': questions,
        }, self.cfg.openrouter_api_key)

    def chat(self, messages):
        self._require_key()
        return self._post(self.cfg.chat_url, {
            'model': self.cfg.luna_model,
            'messages': messages,
            'provider': {'sort': self.cfg.luna_provider_sort},
            'response_format': {'type': 'json_object'},
        }, self.cfg.openrouter_api_key)

    def _require_key(self):
        if not self.cfg.openrouter_api_key:
            raise PlannerError('OPENROUTER_API_KEY is not set in work/lab-data/lab.env')


def _post(url, body, key):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')[:400]
        raise PlannerError(f'OpenRouter returned {exc.code}: {detail}') from exc
