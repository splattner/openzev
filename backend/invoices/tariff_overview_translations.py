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
        "dynamic_average_label": "Zeitgewichteter dynamischer Durchschnitt",
        "dynamic_partial_label": "Unvollständiger dynamischer Durchschnitt",
        "dynamic_unavailable_label": "Dynamischer Preis nicht verfügbar",
        "dynamic_reference_dates": " ({start} – {end})",
        "fee_per_metering_point": "pro Zählpunkt",
        "fee_shared_equal": "Gemeinschaftskosten, zu gleichen Teilen aufgeteilt",
        "fee_shared_weight": "Gemeinschaftskosten, nach Gewichtung aufgeteilt",
        "footnote_multiband_base": (
            "Der gezeigte Basispreis ist der Tarif ausserhalb der Zeitband-"
            "Einschränkungen. Der effektive Preis richtet sich nach dem im "
            "Verbrauchszeitpunkt geltenden Band."
        ),
        "footnote_dynamic_average": (
            "Dieser Tarif wird über einen dynamischen Preis abgerechnet. Der "
            "gezeigte Preis ist der nach Intervalldauer gewichtete Durchschnitt "
            "aus bis zu 30 Tagen innerhalb der Tarifgültigkeit, kein fester Tarif."
        ),
        "footnote_dynamic_partial": (
            "Die dynamische Preisreihe ist im gezeigten Zeitraum unvollständig. "
            "Der Durchschnitt berücksichtigt nur die vorhandenen Intervalle."
        ),
        "footnote_dynamic_unavailable": (
            "Für den gezeigten Zeitraum wurde kein dynamischer Preis abgerufen. "
            "Deshalb wird kein Ersatzpreis angezeigt."
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
        "dynamic_average_label": "Moyenne dynamique pondérée dans le temps",
        "dynamic_partial_label": "Moyenne dynamique incomplète",
        "dynamic_unavailable_label": "Prix dynamique indisponible",
        "dynamic_reference_dates": " ({start} – {end})",
        "fee_per_metering_point": "par point de mesure",
        "fee_shared_equal": "Frais communs, répartis à parts égales",
        "fee_shared_weight": "Frais communs, répartis selon la pondération",
        "footnote_multiband_base": (
            "Le prix de base indiqué est le tarif en dehors des plages horaires. "
            "Le prix effectif suit la plage en vigueur au moment de la consommation."
        ),
        "footnote_dynamic_average": (
            "Ce tarif est facturé sur la base d'un prix dynamique. Le prix "
            "indiqué est la moyenne pondérée par la durée des intervalles sur "
            "30 jours au plus pendant la validité du tarif, et non un tarif fixe."
        ),
        "footnote_dynamic_partial": (
            "La série de prix dynamique est incomplète pour la période indiquée. "
            "La moyenne ne tient compte que des intervalles disponibles."
        ),
        "footnote_dynamic_unavailable": (
            "Aucun prix dynamique n'a été récupéré pour la période indiquée. "
            "Aucun prix de remplacement n'est donc affiché."
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
        "dynamic_average_label": "Media dinamica ponderata nel tempo",
        "dynamic_partial_label": "Media dinamica incompleta",
        "dynamic_unavailable_label": "Prezzo dinamico non disponibile",
        "dynamic_reference_dates": " ({start} – {end})",
        "fee_per_metering_point": "per punto di misura",
        "fee_shared_equal": "Costi comuni, ripartiti in parti uguali",
        "fee_shared_weight": "Costi comuni, ripartiti secondo la ponderazione",
        "footnote_multiband_base": (
            "Il prezzo di base indicato è la tariffa al di fuori delle fasce "
            "orarie. Il prezzo effettivo segue la fascia in vigore al momento "
            "del consumo."
        ),
        "footnote_dynamic_average": (
            "Questa tariffa viene fatturata in base a un prezzo dinamico. Il "
            "prezzo indicato è la media ponderata per la durata degli intervalli "
            "di un massimo di 30 giorni nella validità tariffaria, non una tariffa fissa."
        ),
        "footnote_dynamic_partial": (
            "La serie di prezzi dinamica è incompleta per il periodo indicato. "
            "La media considera soltanto gli intervalli disponibili."
        ),
        "footnote_dynamic_unavailable": (
            "Non è stato recuperato alcun prezzo dinamico per il periodo indicato. "
            "Non viene quindi mostrato un prezzo sostitutivo."
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
        "dynamic_average_label": "Time-weighted dynamic average",
        "dynamic_partial_label": "Incomplete dynamic average",
        "dynamic_unavailable_label": "Dynamic price unavailable",
        "dynamic_reference_dates": " ({start} – {end})",
        "fee_per_metering_point": "per metering point",
        "fee_shared_equal": "Community costs, split equally",
        "fee_shared_weight": "Community costs, split by weight",
        "footnote_multiband_base": (
            "The base price shown is the tariff outside its time-band "
            "restrictions. The effective price follows whichever band applies "
            "at the time of consumption."
        ),
        "footnote_dynamic_average": (
            "This tariff is billed from a dynamic price. The price shown is "
            "weighted by interval duration over up to 30 days within the tariff's "
            "validity; it is not a fixed rate."
        ),
        "footnote_dynamic_partial": (
            "The dynamic price series is incomplete for the period shown. The "
            "average uses only the intervals that are available."
        ),
        "footnote_dynamic_unavailable": (
            "No dynamic price was fetched for the period shown, so no substitute "
            "price is displayed."
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
