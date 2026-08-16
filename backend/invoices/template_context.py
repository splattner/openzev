"""
Pure helpers for building sample/preview template contexts.

These functions produce realistic-looking placeholder data used by the
pdf-template, contract-pdf-template, and annual-statement-pdf-template
preview endpoints in views.py. They have no side effects and no Django
request dependency, so they live here rather than in views.py.
"""

from .annual_statement import ANNUAL_TRANSLATIONS, _build_monthly_chart_svg
from .contract_translations import CONTRACT_TRANSLATIONS
from .pdf_translations import INVOICE_TRANSLATIONS


class _Obj:
    """Simple namespace that allows attribute access on a dict."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __str__(self):
        return self.__dict__.get("_str", "")

    def get_status_display(self):
        return self.__dict__.get("_status_display", "Draft")

    def get_zev_type_display(self):
        return self.__dict__.get("_zev_type_display", "vZEV")

    def get_full_name(self):
        return self.__dict__.get("_full_name", "")


def build_sample_invoice_context() -> dict:
    tr = dict(INVOICE_TRANSLATIONS.get("en", INVOICE_TRANSLATIONS["de"]))
    tr["notes_question"] = tr["notes_question"].format(email="info@example.com")
    return {
        "invoice": _Obj(
            invoice_number="INV-2026-001",
            _status_display="Draft",
            subtotal_chf="450.00",
            vat_rate="8.1",
            vat_chf="36.45",
            total_chf="486.45",
            notes="Sample invoice for template preview.",
            zev=_Obj(invoice_language="en"),
        ),
        "grouped_items": [
            {
                "key": "energy",
                "label": tr["cat_energy"],
                "items": [
                    _Obj(description="Local ZEV energy Jan 2026", quantity_kwh="320.50", unit="kWh", unit_label="kWh", unit_price_chf="0.18", total_chf="57.69"),
                    _Obj(description="Grid energy Jan 2026", quantity_kwh="180.00", unit="kWh", unit_label="kWh", unit_price_chf="0.22", total_chf="39.60"),
                ],
                "subtotal": "97.29",
            },
            {
                "key": "grid_fees",
                "label": tr["cat_grid_fees"],
                "items": [
                    _Obj(description="Grid usage fee Jan 2026", quantity_kwh="500.50", unit="kWh", unit_label="kWh", unit_price_chf="0.08", total_chf="40.04"),
                ],
                "subtotal": "40.04",
            },
        ],
        "zev": _Obj(
            name="Solar Community Example",
            vat_number="CHE-123.456.789",
            bank_iban="CH93 0076 2011 6238 5295 7",
        ),
        "owner_participant": _Obj(
            full_name="Maria Muster",
            address_line1="Solarweg 1",
            address_line2="",
            postal_code="8000",
            city="Zürich",
        ),
        "participant": _Obj(
            full_name="Hans Beispiel",
            address_line1="Musterstrasse 42",
            postal_code="3000",
            city="Bern",
            email="hans@example.com",
        ),
        "qr_svg": None,
        "energy_chart_svg": None,
        "hourly_profile_chart_svg": None,
        "energy_flow_svg": None,
        "energy_summary": {
            "local_kwh": "320.50",
            "grid_kwh": "180.00",
            "total_kwh": "500.50",
            "local_share_pct": "64.1",
        },
        "invoice_number_prefix": "INV-2026-",
        "invoice_number_suffix": "001",
        "inline_qr_payment": False,
        "savings_data": {
            "local_kwh": "320.50",
            "local_chf": "57.69",
            "local_rp": "18.00",
            "grid_rp": "22.00",
            "saved_rp": "4.00",
            "hypothetical_chf": "70.51",
            "saved_chf": "12.82",
            "bar_pct": "81.8",
            "savings_bar_pct": "18.2",
        },
        "tr": tr,
        "status_display": tr["status_values"]["draft"],
        "formatted_dates": {
            "invoice_date": "15.01.2026",
            "period_start": "01.01.2026",
            "period_end": "31.01.2026",
            "due_date": "14.02.2026",
        },
    }


def build_sample_contract_context() -> dict:
    tr = dict(CONTRACT_TRANSLATIONS.get("en", CONTRACT_TRANSLATIONS["de"]))
    tr["privacy_retention_rows"] = list(
        zip(tr["privacy_retention_categories"], tr["privacy_retention_periods"])
    )
    # Mirrors _build_contract_context: the payment-term unit is derived from
    # the ZEV's payment term days.
    tr["payment_terms_unit"] = tr["payment_terms_unit_pl"]
    return {
        "participant": _Obj(
            full_name="Hans Beispiel",
            address_line1="Musterstrasse 42",
            address_line2="",
            postal_code="3000",
            city="Bern",
            phone="+41 31 123 45 67",
            email="hans@example.com",
        ),
        "owner_participant": _Obj(
            full_name="Maria Muster",
            address_line1="Solarweg 1",
            address_line2="",
            postal_code="8000",
            city="Zürich",
            phone="+41 44 987 65 43",
            email="maria@example.com",
        ),
        "zev": _Obj(
            name="Solar Community Example",
            _zev_type_display="vZEV",
            grid_operator="Stadtwerk Zürich",
            vat_number="CHE-123.456.789",
            bank_iban="CH93 0076 2011 6238 5295 7",
            payment_term_days=30,
            owner=_Obj(
                _full_name="Maria Muster",
                username="maria",
                email="maria@example.com",
            ),
        ),
        "consumption_mps": [
            _Obj(meter_id="CH1008845123456000000000000012345", location_description="Apartment 3B"),
        ],
        "production_mps": [
            _Obj(meter_id="CH1008845123456000000000000054321", location_description="Rooftop PV system"),
        ],
        "local_tariff_rows": [
            {
                "name": "Local solar tariff",
                "rate_rp": "18.00",
                "unit": tr["tariff_rp_unit"],
                "pct": "80.00",
                "rate_description": "80.00% × 22.50 Rp./kWh (% of grid tariff)",
                "valid_from": "01.01.2026",
                "valid_to": "31.12.2026",
                "validity": "01.01.2026 – 31.12.2026",
                "notes": "EKZ Standardprodukt der Grundversorgung",
            },
        ],
        "tariff_pct_line": tr["tariff_pct_of"].format(pct="80.00"),
        "tariff_rule": tr["clause_tariff_rule_pct"].format(pct="80.00"),
        "tariff_reference_product": "EKZ Standardprodukt der Grundversorgung",
        "billing_interval_display": "Quarterly",
        "contract_date": "01.01.2026",
        "participation_start": "01.01.2026",
        "document_id": "CTR-3B7A9C21",
        "vat_rate_display": "8.10 %",
        "tr": tr,
        "lang": "en",
        "local_tariff_notes": "The tariff follows the tariff rule in section 5 and adjusts automatically when the grid operator changes its prices.",
        "additional_contract_notes": "Participant agrees to the general terms and conditions of the ZEV.",
        "is_preview": True,
    }


def build_sample_annual_statement_context() -> dict:
    tr = ANNUAL_TRANSLATIONS.get("en", ANNUAL_TRANSLATIONS["de"])
    monthly_data = []
    for i, month in enumerate(tr["months"]):
        consumed = 320.0 + i * 15
        from_zev = consumed * 0.62
        from_grid = consumed - from_zev
        produced = 80.0 + i * 10 if i < 6 else 80.0 + (11 - i) * 10
        self_suf = round(from_zev / consumed * 100) if consumed > 0 else 0
        monthly_data.append({
            "month_label": month,
            "consumed_kwh": f"{consumed:.2f}",
            "from_zev_kwh": f"{from_zev:.2f}",
            "from_grid_kwh": f"{from_grid:.2f}",
            "produced_kwh": f"{produced:.2f}",
            "self_sufficiency_pct": self_suf,
        })
    total_consumed = sum(float(m["consumed_kwh"]) for m in monthly_data)
    total_from_zev = sum(float(m["from_zev_kwh"]) for m in monthly_data)
    total_from_grid = sum(float(m["from_grid_kwh"]) for m in monthly_data)
    total_produced = sum(float(m["produced_kwh"]) for m in monthly_data)
    return {
        "lang": "en",
        "tr": tr,
        "year": 2025,
        "zev": _Obj(
            name="Solar Community Example",
            vat_number="CHE-123.456.789",
        ),
        "participant": _Obj(
            full_name="Hans Beispiel",
            address_line1="Musterstrasse 42",
            address_line2="",
            postal_code="3000",
            city="Bern",
        ),
        "owner_participant": _Obj(
            full_name="Maria Muster",
            address_line1="Solarweg 1",
            address_line2="",
            postal_code="8000",
            city="Zürich",
        ),
        "monthly_data": monthly_data,
        "totals": {
            "total_consumed_kwh": f"{total_consumed:.2f}",
            "from_zev_kwh": f"{total_from_zev:.2f}",
            "from_grid_kwh": f"{total_from_grid:.2f}",
            "total_produced_kwh": f"{total_produced:.2f}",
            "self_sufficiency_pct": round(total_from_zev / total_consumed * 100) if total_consumed > 0 else 0,
        },
        "monthly_chart_svg": _build_monthly_chart_svg(monthly_data, tr),
        "invoices": [
            {
                "invoice_number": "INV-2025-001",
                "period_start_formatted": "01.01.2025",
                "period_end_formatted": "31.03.2025",
                "subtotal_chf": "450.00",
                "vat_chf": "36.45",
                "total_chf": "486.45",
            },
            {
                "invoice_number": "INV-2025-002",
                "period_start_formatted": "01.04.2025",
                "period_end_formatted": "30.06.2025",
                "subtotal_chf": "520.00",
                "vat_chf": "42.12",
                "total_chf": "562.12",
            },
            {
                "invoice_number": "INV-2025-003",
                "period_start_formatted": "01.07.2025",
                "period_end_formatted": "30.09.2025",
                "subtotal_chf": "380.00",
                "vat_chf": "30.78",
                "total_chf": "410.78",
            },
            {
                "invoice_number": "INV-2025-004",
                "period_start_formatted": "01.10.2025",
                "period_end_formatted": "31.12.2025",
                "subtotal_chf": "490.00",
                "vat_chf": "39.69",
                "total_chf": "529.69",
            },
        ],
        "invoice_totals": {
            "subtotal_chf": "1840.00",
            "vat_chf": "149.04",
            "total_chf": "1989.04",
        },
        "savings": {
            "local_kwh": "2976.00",
            "local_chf": "535.68",
            "local_rp": "18.00",
            "grid_rp": "22.00",
            "hypothetical_chf": "654.72",
            "saved_chf": "119.04",
        },
        "formatted_dates": {
            "statement_date": "01.01.2026",
        },
    }
