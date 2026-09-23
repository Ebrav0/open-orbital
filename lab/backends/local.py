"""On-box worker processes. Each process claims one shard and exits."""
import subprocess
import sys

from lab.backends.base import Backend


class LocalBackend(Backend):
    name = 'local'

    def __init__(self, popen=None):
        self.popen = popen or subprocess.Popen
        self.procs = []

    def launch(self, count, context):
        started = []
        for _ in range(count):
            proc = self.popen([sys.executable, '-m', 'lab', 'worker', '--once', '--backend', 'local'])
            self.procs.append(proc)
            started.append(str(proc.pid))
        return started

    def active_count(self):
        self.procs = [proc for proc in self.procs if proc.poll() is None]
        return len(self.procs)

    def drain(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
