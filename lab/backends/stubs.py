"""Later compute backends. They share the Backend methods and do not run yet."""
from lab.backends.base import Backend, NotConfigured


class _Stub(Backend):
    def launch(self, count, context):
        raise NotConfigured(f'{self.name} is not configured')

    def active_count(self):
        return 0

    def drain(self):
        return None


class OracleBackend(_Stub):
    name = 'oracle'


class ModalBackend(_Stub):
    name = 'modal'


class CodespacesBackend(_Stub):
    name = 'codespaces'


class GoogleSpotBackend(_Stub):
    name = 'google_spot'


STUBS = {
    'oracle': OracleBackend,
    'modal': ModalBackend,
    'codespaces': CodespacesBackend,
    'google_spot': GoogleSpotBackend,
}
