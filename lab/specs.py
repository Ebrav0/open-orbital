"""Structured experiment specs. Matrix expansion lives in safety.expand."""
import json
from pathlib import Path


def read_spec(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError('Spec file must contain one JSON object')
    return data
