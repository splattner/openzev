# ADR 0012: Participant address geocoding via public Nominatim, cached not persisted

- Status: Accepted
- Date: 2026-07-25

## Context

The Participants management page needs a small map showing each participant's building. Participant addresses (`address_line1`, `address_line2`, `postal_code`, `city`) are free-text and optional; there is no `country` field, no existing lat/lng or geocoding data anywhere in the system, and no prior ADR governs sending participant data to a third-party service.

OpenZEV is Swiss-only in practice (the invoice PDF pipeline already hardcodes `"country": "CH"`), so address resolution can safely assume Switzerland without a new region/country field.

The public OpenStreetMap Nominatim API can resolve a street address to the actual mapped building — its real OSM way/relation polygon, not just an axis-aligned bounding box (a building has angled edges; a bounding box would misrepresent it). Its usage policy caps requests at 1/second, requires an identifying `User-Agent`, and — importantly — requires identical repeated requests to be cached rather than re-issued.

## Decision

Geocode participant addresses server-side, on a cache-only basis — no new database columns.

- `zev/geocoding.py` calls Nominatim's structured search (`street`, `postalcode`, `city`, `country=Switzerland`, `polygon_geojson=1`) and only accepts a result as a building if: (a) it's tagged `building`/`house`, or its bounding box is small enough (≤150m diagonal) to plausibly be one building rather than a street/postal-code/city-level fallback match, **and** (b) Nominatim actually returned a `Polygon`/`MultiPolygon` geometry — i.e. the address resolved to a real mapped OSM way/relation, not just a bare address point with no drawn footprint. Anything coarser, unmatched, or geometry-less is treated as "not found."
- The cached (and API-exposed) value is the real GeoJSON geometry — the polygon's actual nodes, in GeoJSON's native `[longitude, latitude]` order — not a derived bounding box. The bounding box is only used internally, transiently, for the size guard above.
- Results are cached in Redis via Django's cache framework (`CACHES["default"]`, a Redis DB distinct from the Celery broker's), keyed by a hash of the normalized address. Positive matches get a long TTL (~180 days, since buildings don't move); negative results get a short TTL (~7 days) so a later-corrected typo isn't stuck.
- A Celery task (`zev/tasks.py::warm_participant_geocode_cache_task`) warms the cache when a participant is created/updated with an address (via `ParticipantSerializer.create/update` and the ZEV-with-owner bootstrap path in `zev/services.py`). It's safe to enqueue unconditionally — the task is a no-op once the address is cached — so no "did the address actually change" diffing is needed.
- `ParticipantSerializer.building_footprint` is a `SerializerMethodField` that reads the cache at serialization time. It never calls Nominatim itself, so API reads stay fast and never touch the network.
- The frontend renders the geometry with react-leaflet's `<GeoJSON>` layer (not a hand-computed `<Rectangle>`), so Leaflet draws the polygon's real, possibly angled, edges — including holes for a `MultiPolygon`, handled natively.
- A management command (`geocode_participants`) backfills the cache for existing participants, sequentially (not bursted), for data that predates this feature.
- Ungeocodable or missing addresses are simply omitted from the map — no manual override UI in this iteration.

Coordinates are treated as a derived, best-effort artifact of an external service, not authoritative participant data — hence cache, not schema.

## Consequences

Positive:
- No migration, no schema lifecycle to maintain for third-party-derived data; re-deriving with a different provider or logic later needs no data migration.
- Address-keyed caching means participants sharing a building (the common case for a single-building vZEV) are geocoded once, not once per participant.
- Compliant with Nominatim's caching and rate-limit requirements by construction — the only path that calls Nominatim is the rate-limited background task, and it never repeats a request for an address it already has an answer for.
- Reads (participant list/detail) never block on or fail because of the external service.

Trade-offs:
- Cache eviction (Redis restart, `FLUSHALL`, memory pressure) silently loses geocoding data; it self-heals on the next create/update of an affected participant, or a re-run of the backfill command, but there's a window with no map data for those participants.
- No manual correction path yet if Nominatim's automatic building match is wrong or missing — deferred to keep this iteration's scope tight.
- The Swiss-only assumption is implicit in the geocoding query, not a stored/validated participant field — an address for a different country would silently geocode incorrectly rather than failing loudly.

## Alternatives considered

1. Store `latitude`/`longitude` (or bbox) as columns on `Participant`, geocoded once and persisted.
   - Rejected: makes a third-party, best-effort value look like authoritative participant data, and requires a migration/backfill lifecycle for something that's fully re-derivable from data already stored (the address fields).
2. Geocode directly from the browser on every page load.
   - Rejected: Nominatim's usage policy requires caching identical repeated requests, which a live-per-page-view browser call would violate; it also couldn't enforce the 1 req/sec limit across concurrent users, and would be slow on first render for any ZEV with more than a handful of participants.
3. One marker per participant using Nominatim's returned centroid `lat`/`lon` instead of the building's outline.
   - Rejected in favor of drawing the actual building footprint, since it's more informative and Nominatim already returns it for a good match.
4. Draw the axis-aligned bounding box as a rectangle instead of the real polygon.
   - Rejected: a building isn't axis-aligned in general, so a bounding-box rectangle would visibly misrepresent its shape and position; Nominatim's `polygon_geojson=1` returns the actual way/relation geometry for free on the same request, so there was no reason to settle for the cruder shape.

## Notes

Nominatim's public server also disallows bulk/heavy automated use. The chosen trigger (geocode only on participant create/update, cache-checked first) keeps normal usage well within that even for large ZEVs; if OpenZEV ever adds bulk participant import with addresses, that path should also warm the cache one participant at a time (already true of the `geocode_participants` backfill command) rather than importing straight into a burst of cache-miss lookups.

### Addendum (2026-09): opt-in via feature flag

This decision shipped with geocoding always on for every instance with participant addresses, which sends those addresses to a public third-party API with no way for an operator to opt out (#796). `FeatureFlag.PARTICIPANT_GEOCODING_ENABLED` now gates it, **default off** — an operator turns it on explicitly (Admin → System Settings → Features) once they've decided that transfer is acceptable for their deployment. The flag is checked in `zev/geocoding.py::warm_geocode_cache`, the single choke point both the Celery task and the `geocode_participants` backfill command go through, and (redundantly, to avoid enqueuing dead work) in `zev/tasks.py::trigger_geocode_if_address_present`. `get_cached_building_footprint` (the read path used at API serialization time) stays ungated — it never calls Nominatim regardless of the flag, so there's nothing there to disable.
