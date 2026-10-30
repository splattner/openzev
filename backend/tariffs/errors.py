"""Add machine-readable diagnostics to tariff errors without replacing DRF fields."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, ValidationError


class ErrorCode(str):
    # DRF rebuilds ErrorDetail during nesting but preserves its code object.
    def __new__(cls, code, params):
        value = super().__new__(cls, code)
        value.params = params
        return value


def error_detail(message, code, **params):
    return ErrorDetail(message, code=ErrorCode(code, params))


def model_error(message, code, **params):
    return DjangoValidationError(
        "%(diagnostic)s", code=code, params={"diagnostic": message, **params}
    )


def model_validation_error(exc):
    def details(errors):
        result = []
        for error in errors:
            params = error.params or {}
            # Django validators also carry model objects; only expose contract parameters.
            safe = {
                key: params[key]
                for key in ("name", "date", "months", "billing_mode")
                if key in params
            }
            if "max" in params:
                safe["count"] = params["max"]
            if "limit_value" in params:
                safe["value"] = params["limit_value"]
            result.append(
                error_detail(error.messages[0], error.code or "invalid", **safe)
            )
        return result

    return ValidationError(
        {field: details(errors) for field, errors in exc.error_dict.items()}
        if hasattr(exc, "error_dict")
        else details(exc.error_list)
    )


def _annotate_fields(detail, field):
    if isinstance(detail, dict):
        for key, value in detail.items():
            child = getattr(field, "fields", {}).get(key)
            if child is not None:
                _annotate_fields(value, child)
    elif isinstance(detail, list):
        for value in detail:
            _annotate_fields(value, getattr(field, "child", field))
    elif isinstance(detail, ErrorDetail):
        code = detail.code
        params = dict(getattr(code, "params", {}))
        if code == "invalid":
            for kind, name in (
                (serializers.DateField, "invalid_date"),
                (serializers.TimeField, "invalid_time"),
                (serializers.DecimalField, "invalid_number"),
                (serializers.IntegerField, "invalid_number"),
                (serializers.URLField, "invalid_url"),
            ):
                if isinstance(field, kind):
                    code = name
                    break
        attributes = {
            "max_digits": ("count", "max_digits"),
            "max_decimal_places": ("count", "decimal_places"),
            "max_whole_digits": ("count", "max_whole_digits"),
            "max_length": ("count", "max_length"),
            "min_length": ("count", "min_length"),
            "min_value": ("value", "min_value"),
            "max_value": ("value", "max_value"),
        }
        if code in attributes:
            key, attribute = attributes[code]
            value = getattr(field, attribute, None)
            if value is not None:
                params[key] = value
        detail.code = ErrorCode(code, params)


class TariffValidationMixin:
    def run_validation(self, data=serializers.empty):
        try:
            return super().run_validation(data)
        except ValidationError as exc:
            _annotate_fields(exc.detail, self)
            mode = (
                data.get("billing_mode") if isinstance(data, dict) else None
            ) or getattr(self.instance, "billing_mode", None)
            for detail in _error_entries(exc.detail):
                if detail["field"] == "fixed_price_chf" and mode:
                    detail["error"].code.params["billing_mode"] = mode
            raise


def _error_entries(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _error_entries(child, (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _error_entries(
                child, (*path, index) if isinstance(child, (dict, list)) else path
            )
    elif isinstance(value, str) and value.strip():
        field = next((key for key in reversed(path) if isinstance(key, str)), None)
        yield {
            "path": list(path),
            "field": field
            if field not in {"detail", "non_field_errors", "__all__"}
            else None,
            "error": value,
        }


class TariffErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    field = serializers.CharField(allow_null=True)
    path = serializers.ListField(child=serializers.JSONField())
    params = serializers.DictField()
    message = serializers.CharField()


class TariffErrorResponseSerializer(serializers.Serializer):
    validation_errors = TariffErrorSerializer(many=True)


class TariffErrorSchema(AutoSchema):
    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction)
        for code in ("400", "401", "403", "404", "409", "503"):
            responses.setdefault(
                code,
                self._get_response_for_code(
                    TariffErrorResponseSerializer, code, direction=direction
                ),
            )
        return responses


class TariffErrorResponseMixin:
    schema = TariffErrorSchema()

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            exc = model_validation_error(exc)
            if hasattr(self, "get_serializer"):
                _annotate_fields(exc.detail, self.get_serializer())
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        if response.status_code >= 400:
            errors = []
            for entry in _error_entries(response.data):
                error = entry.pop("error")
                code = getattr(error, "code", "unknown")
                errors.append(
                    {
                        **entry,
                        "code": str(code),
                        "params": getattr(code, "params", {}),
                        "message": str(error),
                    }
                )
            data = (
                response.data
                if isinstance(response.data, dict)
                else {"detail": response.data}
            )
            response.data = {**data, "validation_errors": errors}
        return super().finalize_response(request, response, *args, **kwargs)
