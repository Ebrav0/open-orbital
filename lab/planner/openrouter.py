"""OpenRouter JSON calls for Luna planning and Jev's constrained decisions."""
import json
import urllib.error
import urllib.request


class PlannerError(RuntimeError):
    pass


class OpenRouter:
    def __init__(self, cfg, post=None):
        self.cfg = cfg
        self._post = post or _post

    def decisions(self, state, questions):
        """Retained for the original NOUL prototype; new planning uses structured chat."""
        self._require_key()
        return self._post(self.cfg.decisions_url, {
            'model': self.cfg.jev_model,
            'state': state,
            'questions': questions,
        }, self.cfg.openrouter_api_key)

    def chat(self, messages, model=None, temperature=0):
        self._require_key()
        return self._post(self.cfg.chat_url, {
            'model': model or self.cfg.luna_model,
            'messages': messages,
            'temperature': temperature,
            'provider': {'sort': self.cfg.luna_provider_sort} if (model or self.cfg.luna_model) == self.cfg.luna_model else {},
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
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')[:400]
        raise PlannerError(f'OpenRouter returned {exc.code}: {detail}') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PlannerError(f'OpenRouter request failed: {exc}') from exc
