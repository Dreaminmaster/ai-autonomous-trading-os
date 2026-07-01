class ProductionGuard:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def assert_enabled(self) -> None:
        if not self.enabled:
            raise PermissionError('Production boundary disabled by default')

    def execute(self, *args, **kwargs):
        self.assert_enabled()
        raise NotImplementedError('Connect external adapter locally behind this guard')
