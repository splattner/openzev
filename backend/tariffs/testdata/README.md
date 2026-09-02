# Tariff import test fixtures

## `vse_tariffs_iwm_2027.json`

The 2027 tariff publication of **InfraWerke Münsingen**, downloaded unmodified
from the operator's own website on 2026-09-02:

<https://www.inframuensingen.ch/download/documents/bf/h3rv2u71ajxbkrni50earqunmau44c/tarife_2027_iwm.json>

It is here because a fixture written to match the importer proves only that the
importer matches itself. This is a document a Swiss grid operator actually
published under Art. 7b StromVV — 23 entries, including the constant, two-price
multilevel, metering and municipal-surcharge shapes, and the `0.00` placeholder
components real documents are full of.

Grid operators are legally obliged to publish this document at a freely
accessible address, so redistributing it alongside the code that reads it is
within the purpose it was published for. Refresh it (or add another operator's)
by downloading the file as-is — do not hand-edit it, or it stops being evidence
of anything.

Synthetic documents for shapes this one does not contain — seasonal prices,
dynamic tariffs, three-price bands, the NNMV-CH annex's drifted spellings —
are built inline in `tariffs/test_vse_import.py`.
