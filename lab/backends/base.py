class NotConfigured(RuntimeError):
    pass


class Backend:
    name = 'backend'

    def launch(self, count, context):
        raise NotImplementedError

    def active_count(self):
        raise NotImplementedError

    def drain(self):
        raise NotImplementedError
