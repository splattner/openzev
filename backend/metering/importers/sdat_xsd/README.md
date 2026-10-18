# Vendored SDAT-CH XML schemas (read-only)

Dependency bundle for offline E66 validation. Vendoring these files does not change importer behavior.

- `ValidatedMeteredData_1p6.xsd` is the entry schema (SDAT-CH 2025,
  mandatory in Switzerland since 24.03.2026).
- The other 53 files are its transitive `xs:import`/`xs:include` closure
  (ebIX / UNECE / VSE code lists, eCH types), copied unchanged from the
  official VSE `Beispieldateien` archive so validation works offline
  (`no_network=True`); relative `schemaLocation` imports resolve from
  this directory.

© VSE/AES, ebIX, UNECE. Do not edit vendored files; replace the whole
directory when a new SDAT-CH edition ships.

Source: [VSE SDAT-CH 2025 example archive](https://www.strom.ch/de/media/13704/download),
SHA-256 `7d715163f1ab7cb2f0e0e5d9d3b8ddb9dc6a4a7786edda459b70eb4492019a3f`.
Keep the notices/permission paragraphs embedded in each schema; the eCH
schemas have their own provenance. All 54 files are reachable dependencies.

libxml2 rejects one prohibited attribute's inline type in
`ValidatedMeteredData_CoreComponents_1p6.xsd`. Consumers should resolve that file
through an in-memory normalization while compiling once under a thread lock,
without rewriting vendor files or creating a temporary schema directory.

Dependency attribution: the three eCH schemas are `eCH-0010-7-0.xsd`
(postal addresses, 7.0), `eCH-0044-4-1.xsd` (person identification, 4.1)
and `eCH-0046-5-0.xsd` (contact data, 5.0), supplied in the same pinned VSE
archive. Their publisher is [Verein eCH](https://www.ech.ch/de/standard-uebersicht).
The other 51 schemas contain copying/distribution permission paragraphs;
retain those paragraphs and all author notices. These dependencies retain
their own terms rather than being relicensed under the application license.
