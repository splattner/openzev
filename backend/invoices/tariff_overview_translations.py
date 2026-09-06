"""Tariff overview PDF translations — pure data, no logic.

Category labels (Energie / Netzgebühren / Abgaben / Messtarif) are
deliberately *not* duplicated here — the context builder reads them from
``INVOICE_TRANSLATIONS`` so the overview and the invoice cannot describe the
same category with two different words.
"""

TARIFF_OVERVIEW_TRANSLATIONS: dict[str, dict] = {
    "de": {
        "document_label": "Tarifübersicht",
        "all_versions": "Alle Versionen",
        "vat_label": "MWST",
        "vat_not_registered": "Nicht MWST-pflichtig",
        "vat_registered": "MWST-pflichtig",
        "vat_inclusive": "MWST inklusive",
        "vat_note_registered": "Alle Preise verstehen sich exklusive MWST.",
        "vat_note_inclusive": (
            "Die Preise sind netto ausgewiesen. Auf der Rechnung wird die MWST "
            "aufgeschlagen, da sie in den bezogenen Vorleistungen bereits enthalten ist."
        ),
        "valid_open": "ab {date}",
        "valid_span": "{start} – {end}",
        "no_tariffs": "Für dieses Datum sind keine Tarife konfiguriert.",
        "unit_rp": "Rp./kWh",
        "unit_chf_month": "CHF/Mt.",
        "unit_chf_year": "CHF/Jahr",
        "unit_percent": "%",
        "fee_per_metering_point": "pro Zählpunkt",
        "fee_shared_equal": "Gemeinschaftskosten, zu gleichen Teilen aufgeteilt",
        "fee_shared_weight": "Gemeinschaftskosten, nach Gewichtung aufgeteilt",
        "footnote_multiband_base": (
            "Der gezeigte Basispreis ist der Tarif ausserhalb der Zeitband-"
            "Einschränkungen. Der effektive Preis richtet sich nach dem im "
            "Verbrauchszeitpunkt geltenden Band."
        ),
        "billing_modes": {
            "energy": "Nach Energie",
            "percentage_of_energy": "Prozentsatz der Energietarife",
            "monthly_fee": "Monatliche Gebühr",
            "yearly_fee": "Jahresgebühr",
            "per_metering_point_monthly_fee": "Monatliche Gebühr pro Zählpunkt",
            "per_metering_point_yearly_fee": "Jahresgebühr pro Zählpunkt",
            "shared_monthly_fee": "Geteilte Monatsgebühr",
            "shared_yearly_fee": "Geteilte Jahresgebühr",
        },
    },
    "fr": {
        "document_label": "Aperçu des tarifs",
        "all_versions": "Toutes les versions",
        "vat_label": "TVA",
        "vat_not_registered": "Non assujetti à la TVA",
        "vat_registered": "Assujetti à la TVA",
        "vat_inclusive": "TVA incluse",
        "vat_note_registered": "Tous les prix s'entendent hors TVA.",
        "vat_note_inclusive": (
            "Les prix indiqués sont nets. La TVA est ajoutée sur la facture, "
            "car elle est déjà comprise dans les prestations en amont."
        ),
        "valid_open": "dès le {date}",
        "valid_span": "{start} – {end}",
        "no_tariffs": "Aucun tarif n'est configuré pour cette date.",
        "unit_rp": "cts/kWh",
        "unit_chf_month": "CHF/mois",
        "unit_chf_year": "CHF/an",
        "unit_percent": "%",
        "fee_per_metering_point": "par point de mesure",
        "fee_shared_equal": "Frais communs, répartis à parts égales",
        "fee_shared_weight": "Frais communs, répartis selon la pondération",
        "footnote_multiband_base": (
            "Le prix de base indiqué est le tarif en dehors des plages horaires. "
            "Le prix effectif suit la plage en vigueur au moment de la consommation."
        ),
        "billing_modes": {
            "energy": "Selon l'énergie",
            "percentage_of_energy": "Pourcentage des tarifs d'énergie",
            "monthly_fee": "Redevance mensuelle",
            "yearly_fee": "Redevance annuelle",
            "per_metering_point_monthly_fee": "Redevance mensuelle par point de mesure",
            "per_metering_point_yearly_fee": "Redevance annuelle par point de mesure",
            "shared_monthly_fee": "Redevance mensuelle partagée",
            "shared_yearly_fee": "Redevance annuelle partagée",
        },
    },
    "it": {
        "document_label": "Panoramica tariffe",
        "all_versions": "Tutte le versioni",
        "vat_label": "IVA",
        "vat_not_registered": "Non soggetto a IVA",
        "vat_registered": "Soggetto a IVA",
        "vat_inclusive": "IVA inclusa",
        "vat_note_registered": "Tutti i prezzi si intendono IVA esclusa.",
        "vat_note_inclusive": (
            "I prezzi indicati sono netti. L'IVA viene aggiunta sulla fattura, "
            "poiché è già inclusa nelle prestazioni a monte."
        ),
        "valid_open": "dal {date}",
        "valid_span": "{start} – {end}",
        "no_tariffs": "Per questa data non sono configurate tariffe.",
        "unit_rp": "ct/kWh",
        "unit_chf_month": "CHF/mese",
        "unit_chf_year": "CHF/anno",
        "unit_percent": "%",
        "fee_per_metering_point": "per punto di misura",
        "fee_shared_equal": "Costi comuni, ripartiti in parti uguali",
        "fee_shared_weight": "Costi comuni, ripartiti secondo la ponderazione",
        "footnote_multiband_base": (
            "Il prezzo di base indicato è la tariffa al di fuori delle fasce "
            "orarie. Il prezzo effettivo segue la fascia in vigore al momento "
            "del consumo."
        ),
        "billing_modes": {
            "energy": "Per energia",
            "percentage_of_energy": "Percentuale delle tariffe energetiche",
            "monthly_fee": "Tariffa mensile",
            "yearly_fee": "Tariffa annuale",
            "per_metering_point_monthly_fee": "Tariffa mensile per punto di misura",
            "per_metering_point_yearly_fee": "Tariffa annuale per punto di misura",
            "shared_monthly_fee": "Tariffa mensile condivisa",
            "shared_yearly_fee": "Tariffa annuale condivisa",
        },
    },
    "en": {
        "document_label": "Tariff overview",
        "all_versions": "All versions",
        "vat_label": "VAT",
        "vat_not_registered": "Not VAT-registered",
        "vat_registered": "VAT-registered",
        "vat_inclusive": "VAT inclusive",
        "vat_note_registered": "All prices are exclusive of VAT.",
        "vat_note_inclusive": (
            "Prices shown are net. VAT is added on the invoice, because it is "
            "already included in the upstream services purchased."
        ),
        "valid_open": "from {date}",
        "valid_span": "{start} – {end}",
        "no_tariffs": "No tariffs are configured for this date.",
        "unit_rp": "Rp./kWh",
        "unit_chf_month": "CHF/mo.",
        "unit_chf_year": "CHF/yr.",
        "unit_percent": "%",
        "fee_per_metering_point": "per metering point",
        "fee_shared_equal": "Community costs, split equally",
        "fee_shared_weight": "Community costs, split by weight",
        "footnote_multiband_base": (
            "The base price shown is the tariff outside its time-band "
            "restrictions. The effective price follows whichever band applies "
            "at the time of consumption."
        ),
        "billing_modes": {
            "energy": "By energy",
            "percentage_of_energy": "Percentage of energy tariffs",
            "monthly_fee": "Monthly fee",
            "yearly_fee": "Yearly fee",
            "per_metering_point_monthly_fee": "Monthly fee per metering point",
            "per_metering_point_yearly_fee": "Yearly fee per metering point",
            "shared_monthly_fee": "Shared monthly fee",
            "shared_yearly_fee": "Shared yearly fee",
        },
    },
}
