"""Dispatch GitHub-hosted runners. The workflow file is the only entry point."""
import json
import urllib.error
import urllib.request
import uuid

from lab.backends.base import Backend, NotConfigured


class PartialDispatchError(NotConfigured):
    def __init__(self, message, started):
        super().__init__(message)
        self.started = list(started)


class GitHubBackend(Backend):
    name = 'github'

    def __init__(self, cfg, post=None, active=None):
        self.cfg = cfg
        self._post = post or _post
        self._active = active or (lambda: 0)

    def launch(self, count, context):
        if not self.cfg.github_token:
            raise NotConfigured('LAB_GITHUB_TOKEN is not set in work/lab-data/lab.env')
        url = self.cfg.tailscale_host or context.get('coordinator_url')
        if not url:
            raise NotConfigured('tailscale_host is empty, so a runner has no coordinator URL')
        commit = str(context.get('git_commit') or '')
        if len(commit) != 40 or any(ch not in '0123456789abcdef' for ch in commit.lower()):
            raise NotConfigured('GitHub dispatch requires the exact 40-character experiment commit SHA')
        if not str(url).startswith('http'):
            url = f'http://{url}:{self.cfg.port}'
        started = []
        endpoint = f'https://api.github.com/repos/{self.cfg.github_repo}/actions/workflows/{self.cfg.github_workflow}/dispatches'
        for _ in range(count):
            try:
                self._post(endpoint, {
                    'ref': self.cfg.github_ref,
                    'inputs': {'coordinator_url': url, 'commit_sha': commit},
                }, self.cfg.github_token)
            except Exception as exc:
                if started:
                    raise PartialDispatchError(str(exc), started) from exc
                raise
            started.append(f'dispatch-{uuid.uuid4().hex[:12]}')
        return started

    def active_count(self):
        return self._active()

    def drain(self):
        return None


def _post(url, body, token):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
            'X-GitHub-Api-Version': '2022-11-28',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')[:400]
        raise NotConfigured(f'GitHub dispatch failed ({exc.code}): {detail}') from exc
