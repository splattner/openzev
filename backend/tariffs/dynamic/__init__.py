"""Dynamic tariffs: prices fetched from an operator's time-series API.

A static tariff carries its price in ``TariffPeriod`` rows — a recurring daily
pattern. A dynamic one carries no price at all: the operator publishes it per
quarter-hour on an HTTP endpoint, and OpenZEV fetches and stores it.

The layering here mirrors ``tariffs/importers/``: :mod:`vse_v1` parses, knowing
nothing about the database or the network; :mod:`adapters` knows one operator's
quirks; :mod:`fetch` does the I/O and the writing.
"""
