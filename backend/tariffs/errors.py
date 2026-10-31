"""Preserve tariff field errors and wrap root messages alongside coded diagnostics.

Model parameters are allowlisted; ErrorCode carries them through DRF nesting.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, ValidationError


LIMIT_FIELD_PARAMS = {
    "max_digits": ("count", "max_digits"),
    "max_decimal_places": ("count", "decimal_places"),
    "max_whole_digits": ("count", "max_whole_digits"),
    "max_length": ("count", "max_length"),
    "min_length": ("count", "min_length"),
    "min_value": ("value", "min_value"),
    "max_value": ("value", "max_value"),
}


class ErrorCode(str):
    # DRF rebuilds ErrorDetail during nesting but preserves its code object.
    def __new__(cls, code, params):
        value = super().__new__(cls, code)
        value.params = {
            key: format(item, "f") if isinstance(item, Decimal) else item
            for key, item in params.items()
        }
        return value


def error_detail(message, code, **params):
    return ErrorDetail(message, code=ErrorCode(code, params))


def exception_detail(exc):
    return error_detail(
        str(exc), getattr(exc, "code", "unknown"), **getattr(exc, "params", {})
    )


def model_validation_error(exc, *, serializer=None):
    def details(errors):
        result = []
        for error in errors:
            params = error.params or {}
            # Native validator "value" is the rejected input, not a contract bound.
            # Only model_error supplies explicit value parameters via its diagnostic template.
            public_params = {
                key: params[key]
                for key in (
                    "name",
                    "date",
                    "months",
                    "billing_mode",
                    "count",
                    "value",
                )
                if key in params and (key != "value" or "diagnostic" in params)
            }
            # Django decimal validators use "max"; limit validators use "limit_value".
            if "max" in params:
                public_params["count"] = params["max"]
            if "limit_value" in params:
                key = LIMIT_FIELD_PARAMS.get(error.code, ("value", None))[0]
                public_params[key] = params["limit_value"]
            result.append(
                error_detail(error.messages[0], error.code or "invalid", **public_params)
            )
        return result

    converted = ValidationError(
        {field: details(errors) for field, errors in exc.error_dict.items()}
        if hasattr(exc, "error_dict")
        else details(exc.error_list)
    )
    if serializer is not None:
        annotate_validation_error(converted.detail, serializer)
    return converted


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

        if code in LIMIT_FIELD_PARAMS:
            key, attribute = LIMIT_FIELD_PARAMS[code]
            value = getattr(field, attribute, None)
            if value is not None:
                params[key] = value
        detail.code = ErrorCode(code, params)


def annotate_validation_error(detail, serializer, *, billing_mode=None):
    _annotate_fields(detail, serializer)
    mode = billing_mode or getattr(serializer.instance, "billing_mode", None)
    if mode:
        for entry in _error_entries(detail):
            if entry["field"] == "fixed_price_chf":
                error = entry["error"]
                error.code = ErrorCode(
                    error.code,
                    {**getattr(error.code, "params", {}), "billing_mode": mode},
                )


class TariffValidationMixin:
    def run_validation(self, data=serializers.empty):
        try:
            return super().run_validation(data)
        except ValidationError as exc:
            mode = data.get("billing_mode") if isinstance(data, dict) else None
            annotate_validation_error(exc.detail, self, billing_mode=mode)
            raise


def _error_entries(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            # Root response metadata is not a field error.
            if not path and key in {"code", "validation_errors"}:
                continue
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
    """Legacy DRF field/message properties remain alongside validation_errors."""

    detail = serializers.JSONField(
        required=False, help_text="Legacy non-field messages."
    )
    validation_errors = TariffErrorSerializer(many=True)


class TariffErrorSchema(AutoSchema):
    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction)
        # These hooks are covered by schema tests against pinned drf-spectacular.
        codes = {400, 401, 403}
        if getattr(self.view, "detail", False):
            codes.add(404)
        action = getattr(self.view, "action", self.method.lower())
        codes.update(getattr(self.view, "tariff_error_statuses", {}).get(action, ()))
        for status in sorted(codes):
            code = str(status)
            if code not in responses:
                responses[code] = self._get_response_for_code(
                    TariffErrorResponseSerializer,
                    code,
                    direction=direction,
                )
        return responses


class TariffErrorResponseMixin:
    schema = TariffErrorSchema()

    def handle_exception(self, exc):
        if isinstance(exc, DjangoValidationError):
            exc = model_validation_error(exc)
            if hasattr(self, "get_serializer"):
                annotate_validation_error(exc.detail, self.get_serializer())
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        if response.status_code >= 400 and getattr(response, "data", None) is not None:
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
            if errors:
                response.data = {**data, "validation_errors": errors}
        return super().finalize_response(request, response, *args, **kwargs)
