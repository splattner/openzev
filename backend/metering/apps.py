from django.apps import AppConfig


class MeteringConfig(AppConfig):
    name = 'metering'

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
