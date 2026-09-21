"""Shared constants for the audit app.

``REQUEST_ID_PATTERN`` lives here — rather than in the middleware — so both
the request boundary (``audit.middleware``) and the service boundary
(``audit.services``) can validate request IDs without one importing the other.
"""

import re

# Accept bounded request IDs only; anything else gets a server UUID.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
