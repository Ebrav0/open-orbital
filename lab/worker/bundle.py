"""Pack the observatory resume bundle. control.json is left out so resume starts running."""
import json
import tarfile
from pathlib import Path


NAMES = (
    'config.json', 'meta.json', 'checkpoint.json', 'status.json', 'diagnostics.jsonl',
    'model_source.py', 'stellar_source.py', 'galaxy_index.bin',
)


class BundleError(RuntimeError):
    pass


def pack(run_dir, dest):
    run_dir = Path(run_dir)
    pointer_path = run_dir / 'checkpoint.json'
    if not pointer_path.is_file():
        raise BundleError('no checkpoint.json to publish')
    pointer = json.loads(pointer_path.read_text())
    meta = json.loads((run_dir / 'meta.json').read_text())
    index = int(pointer['index'])
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames = _truncated_frames(run_dir, meta, index)
    with tarfile.open(dest, 'w:gz') as archive:
        for name in NAMES:
            path = run_dir / name
            if path.is_file():
                archive.add(path, arcname=name)
        binary = pointer.get('file') or 'checkpoint.bin'
        archive.add(run_dir / binary, arcname=binary)
        baryons = pointer.get('baryons')
        if baryons:
            archive.add(run_dir / baryons, arcname=baryons)
        if frames is not None:
            archive.add(frames, arcname='frames.bin')
    return dest


def unpack(archive, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            try:
                target.relative_to(dest.resolve())
            except ValueError:
                raise BundleError('archive path escapes the run directory') from None
            if member.issym() or member.islnk():
                raise BundleError('archive links are not allowed')
        tar.extractall(dest)
    (dest / 'control.json').write_text(json.dumps({'action': 'run'}))
    return dest


def _truncated_frames(run_dir, meta, index):
    source = run_dir / 'frames.bin'
    if not source.is_file():
        return None
    stride = int(meta['n']) * int(meta.get('bytes_per_particle') or 16)
    length = (index + 1) * stride
    raw = source.read_bytes()[:length]
    dest = run_dir / 'frames.committed.bin'
    dest.write_bytes(raw)
    return dest
