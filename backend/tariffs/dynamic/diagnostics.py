"""Safe, language-neutral diagnostics shared by storage and API readers."""

FETCH_ERROR_PARAMETERS = {
    "host_unresolved": ("host",),
    "http_status": ("status",),
    "download_failed": (),
    "invalid_url": (),
    "public_url": (),
    "import_url": (),
    "import_json": (),
    "document_size": ("size",),
    "invalid_dynamic_response": (),
    "billed_price_changed": (),
    "price_series_conflict": (),
    "product_required": (),
    "timestamp_missing": ("field",),
    "timestamp_invalid": ("field", "received"),
    "timestamp_offset_missing": ("field",),
    "component_value_invalid": ("field", "received"),
    "price_interval_invalid": ("start", "end"),
    "price_intervals_overlap": ("start", "end", "other_start", "other_end"),
    "product_response_missing": (),
    "product_mismatch": ("expected", "actual"),
}


def normalize_fetch_diagnostics(value):
    """Keep up to three distinct, allowlisted ``{code, params}`` causes; drop other keys and params."""
    result = []
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict):
            continue
        code, params = entry.get("code"), entry.get("params")
        if not isinstance(code, str) or code not in FETCH_ERROR_PARAMETERS or not isinstance(params, dict):
            continue
        required = FETCH_ERROR_PARAMETERS[code]
        if code == "http_status" and (
            type(params.get("status")) is not int or not 100 <= params["status"] <= 599
        ):
            continue
        if code == "document_size":
            size = params.get("size")
            if type(size) not in (int, float) or not 0 <= size <= 2**53 - 1:
                continue
        if any(not isinstance(params.get(key), str) or not params[key].strip()
               for key in required if key not in {"status", "size"}):
            continue
        diagnostic = {"code": code, "params": {key: params[key] for key in required}}
        if diagnostic not in result:
            result.append(diagnostic)
        if len(result) == 3:
            break
    return result
