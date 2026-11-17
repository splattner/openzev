"""Optional UI codes alongside the existing English import messages."""

from decimal import Decimal


class UiNotice(str):
    """An English message that also carries a translatable ``code`` and ``params``.

    It stays a ``str`` so existing API fields keep their text. Any string
    operation (``str()``, ``+``, f-strings, slicing) returns a plain ``str`` and
    drops the code, so pass the notice itself through to ``notice_data``.
    """

    code: str
    params: dict

    def __new__(cls, message, code="unknown", **params):
        value = super().__new__(cls, message)
        value.code = code
        value.params = {
            key: str(item) if isinstance(item, Decimal) else item for key, item in params.items()
        }
        return value

    @classmethod
    def of(cls, code, template, **params):
        """Build the English text from ``template`` and the same ``params``."""
        return cls(template.format(**params), code, **params)


def notice_data(value):
    if isinstance(value, Exception) and value.args:
        value = value.args[0]
    return {"code": value.code, "params": value.params} if isinstance(value, UiNotice) else None
