from django.apps import AppConfig


class MeteringConfig(AppConfig):
    name = 'metering'

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
        from .supplementary import solar_manager  # noqa: F401  (registers the Solar Manager provider)
