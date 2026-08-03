from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        # Registers the OpenAPI security schemes. Importing for the side effect
        # is how drf-spectacular extensions are discovered.
        from . import schema  # noqa: F401
