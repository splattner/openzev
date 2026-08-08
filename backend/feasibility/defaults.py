"""Default assumptions for the vZEV feasibility calculator.

Rough Swiss planning-stage figures so the calculator form is useful before a
user enters anything, or before a real ZEV's prefill (see ``prefill.py``)
can determine a figure from actual tariffs/metering data.
"""
from decimal import Decimal

RETAIL_PRICE_CHF_PER_KWH = Decimal("0.32")
FEED_IN_PRICE_CHF_PER_KWH = Decimal("0.09")
INTERNAL_ENERGY_PRICE_CHF_PER_KWH = Decimal("0.20")
ANNUAL_OPEX_CHF = Decimal("300")
DISCOUNT_RATE = Decimal("0.03")
HORIZON_YEARS = 20

# Fallback for a participant with no metering history at all yet (a brand new
# ZEV) — a rough Swiss household average, clearly flagged to the user as
# estimated rather than measured (see ParticipantPrefill.has_metering_data).
DEFAULT_PARTICIPANT_CONSUMPTION_KWH = Decimal("4500")
