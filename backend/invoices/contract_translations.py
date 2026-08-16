"""
Contract clause translations for the participation agreement PDF.

Pure data module mirroring ``invoices/pdf_translations.py``: the generation
logic lives in ``invoices/contract_pdf.py`` and imports this dict. Keeping
the clause text out of the code module lets lawyers and ZEV managers review
the legal prose without touching rendering code, and keeps the code file at
a size where the logic stays readable.
"""

CONTRACT_TRANSLATIONS: dict[str, dict] = {
    "de": {
        "contract_title": "Teilnahmevertrag vZEV",
        "parties_title": "Vertragsparteien",
        "participant_label": 'Teilnehmer am vZEV (nachfolgend «vZEV-Teilnehmer» genannt)',
        "owner_label": 'vZEV-Verantwortlicher (nachfolgend «vZEV-Verantwortlicher» genannt)',

        "field_address": "Adresse, Ort",
        "field_phone": "Telefon",
        "field_email": "E-Mail",
        "field_meter": "Messpunktnummer",

        "meter_none": "Noch kein Messpunkt zugeordnet",

        "field_meter_pv": "Messpunktnummer (PV / Rückspeisung)",
        "subject_title": "Zweck und Geltungsbereich",
        "subject_text": (
            "Dieser Vertrag regelt die Teilnahme am vZEV und das Innenverhältnis zwischen den Teilnehmern und dem "
            "vZEV-Verantwortlichen gestützt auf die geltende Schweizer Energiegesetzgebung zu "
            "Eigenverbrauchsgemeinschaften (EnG, EnV, Mantelerlass).\n\n"
            "Gegenüber dem Netzbetreiber tritt der vZEV als eine einzige Kundin auf; dieser Vertrag regelt "
            "ausschliesslich die internen Rechte und Pflichten, die interne Stromverteilung und die Abrechnung "
            "der lokalen Energie.\n\n"
            "Dieser Vertrag wird bilateral zwischen dem vZEV-Verantwortlichen und jedem Teilnehmer "
            "abgeschlossen; die inhaltsgleichen Verträge aller Teilnehmer bilden zusammen das interne "
            "Regelwerk des vZEV."
        ),
        "agreements_title": "Vereinbarungen",
        "local_tariff_label": "Ihr Tarif für lokalen Solarstrom",
        "local_tariff_unit": "Rappen / kWh",
        "local_tariff_note": "Weitere Tarifregelungen",
        "local_tariff_note_placeholder": (
            "Beispiel: Der Tarif für lokale ZEV-Energie wird auf 65 % des totalen Netzstrompreises festgelegt "
            "(Energie inkl. Netzkosten, Abgaben etc.). Mindestens jedoch soviel wie die reinen Energiekosten "
            "des Netzbetreibers im jeweiligen Jahr."
        ),
        "tariff_pct_of": "= {pct} % des Standardtarifs des Netzbetreibers",
        "tariff_valid_open": "ab {date}",
        "tariff_valid_label": "Gültigkeit",
        "reference_product_label": "Referenzprodukt",
        "billing_interval_label": "Abrechnungsintervall",
        "payment_terms_label": "Zahlungskonditionen",
        "payment_terms_unit_sg": "Tag ab Rechnungsdatum",
        "payment_terms_unit_pl": "Tage ab Rechnungsdatum",
        "vat_label": "MwSt.",
        "vat_not_required": "Nicht pflichtig",
        "vat_required": "MwSt. pflichtig",
        "additional_label": "Zusätzliche Vereinbarungen",
        "additional_placeholder": (
            "Erfassen Sie allfällige zusätzliche Vereinbarungen, z. B. gewähltes Stromprodukt vom Netzbetreiber "
            "oder Rechnungszustellung per E-Mail."
        ),
        "signatures_title": "Unterschriften",
        "sig_intro": (
            "Mit ihrer Unterschrift bestätigen die Vertragsparteien, den Inhalt dieses Vertrags gelesen und "
            "verstanden zu haben und akzeptieren diesen."
        ),
        "sig_participant": "vZEV-Teilnehmer",
        "sig_owner": "vZEV-Verantwortlicher",
        "sig_place_date": "Ort, Datum",

        "sig_signature": "Unterschrift",
        "page_label": "Seite",
        "page_of": "von",
        "billing_intervals": {
            "monthly": "Monatlich",
            "quarterly": "Quartalsweise",
            "semi_annual": "Halbjährlich",
            "annual": "Jährlich",
        },
        "tariff_ht": "HT (Hochtarif)",
        "tariff_nt": "NT (Niedertarif)",
        "tariff_flat": "Einheitstarif",
        "tariff_pct_prefix": "% des Netzpreises",
        "tariff_rp_unit": "Rp./kWh",
        "tariff_none": "—",
        "tariff_col_name": "Tarif",
        "tariff_col_price": "Preis (Rp./kWh)",
        "tariff_col_calc": "Berechnung",

        "contract_date_label": "Ausstellungsdatum",
        "participation_start_label": "Teilnahmebeginn",
        "appendix_title": "Anhang A – Allgemeine Informationen (unverbindlich; der Vertrag geht vor)",
        "meter_hint": "Die Messpunktnummer ist auf der Stromrechnung zu finden. Sie besteht aus 33 Stellen und beginnt mit CH.",

        "info_subtitle": "Allgemeine Informationen zu Zusammenschlüssen zum Eigenverbrauch",
        "precedence_note": (
            "Dieser Anhang enthält allgemeine, unverbindliche Informationen und ersetzt keine Rechtsberatung. "
            "Bei Widersprüchen gehen die nummerierten Vertragsbestimmungen den Angaben in diesem Anhang vor. "
            "Anhang B ist für die Bearbeitung personenbezogener Daten verbindlich."
        ),
        "info_zev_title": "Was ist ein ZEV?",
        "info_zev_text": (
            "Ein Zusammenschluss zum Eigenverbrauch (ZEV) ermöglicht es Grundeigentümern, den lokal produzierten "
            "Strom (z.\u202fB. aus Solaranlagen) gemeinsam zu nutzen. Die Teilnehmer befinden sich am gleichen "
            "Netzanschluss. Der ZEV tritt gegenüber dem Netzbetreiber als ein einzelner Kunde auf und "
            "organisiert die interne Stromabrechnung selbständig."
        ),
        "info_vzev_title": "Was ist ein virtueller ZEV (vZEV)?",
        "info_vzev_text": (
            "Ein virtueller ZEV (vZEV) erweitert das ZEV-Modell: Die Teilnehmer müssen sich nicht mehr am "
            "gleichen Netzanschlusspunkt befinden. Eine Teilnahme ist jedoch nur zulässig, wenn die gesetzlichen "
            "Voraussetzungen für den Zusammenschluss zum Eigenverbrauch am Ort der Produktion erfüllt sind. "
            "Insbesondere müssen die Nutzung von Anschlussleitungen und der lokalen elektrischen Infrastruktur "
            "am massgeblichen Netzanschlusspunkt nach dem anwendbaren Recht zulässig sein. Die technische "
            "Beurteilung und das Anmelde- und Mutationsverfahren des Netzbetreibers sind massgebend. Jeder "
            "Teilnehmer behält seinen eigenen Netzanschluss. Die Zuteilung des Eigenverbrauchs erfolgt virtuell "
            "anhand von Smart-Meter-Daten."
        ),
        "info_legal_title": "Gesetzliche Grundlagen",
        "info_legal_items": [
            "Energiegesetz (EnG, SR 730.0), Art. 16–18 — Regelungen zum Eigenverbrauch und ZEV",
            "Energieverordnung (EnV, SR 730.01), Art. 14–18 — Ausführungsbestimmungen",
            "Stromversorgungsgesetz (StromVG, SR 734.7) — Netzzugang und Grundversorgung",
            "Bundesgesetz über eine sichere Stromversorgung mit erneuerbaren Energien (Mantelerlass) — "
            "Erweiterung um vZEV (Art. 17a–17c EnG)",
        ],
        "info_rights_title": "Rechte und Pflichten der Teilnehmer",
        "info_rights_items": [
            "Der lokale Stromtarif darf den regulären Netztarif des Netzbetreibers nicht übersteigen.",
            "Austritt und Kündigung richten sich nach Ziffer 10 dieses Vertrags und nach zwingendem Recht, insbesondere "
            "Mietrecht, soweit anwendbar.",
            "Der vZEV-Verantwortliche erstellt die internen Stromabrechnungen und verwaltet den Zusammenschluss.",
            "Änderungen (Wegzug, Eigentümerwechsel) sind dem vZEV-Verantwortlichen unverzüglich zu melden.",
            "Die Grundversorgung durch den Netzbetreiber bleibt für alle Teilnehmer jederzeit gewährleistet.",
        ],
        "info_liability_title": "Solidarische Haftung",
        "info_liability_text": (
            "Alle Teilnehmer eines ZEV bzw. vZEV haften gegenüber dem Netzbetreiber solidarisch für die "
            "Netzkosten und den bezogenen Strom (Art. 17 Abs. 2 EnG). Das bedeutet: Kann ein Teilnehmer seine "
            "Stromrechnung nicht begleichen, können die übrigen Teilnehmer für den ausstehenden Betrag in "
            "Anspruch genommen werden. Die interne Aufteilung der Kosten regelt der vZEV-Verantwortliche "
            "über die Stromabrechnung."
        ),
        "info_tariff_title": "Tarifbestimmungen",
        "info_tariff_text": (
            "Der Tarif für lokal produzierten Strom folgt der Tarifregel in Ziffer 5 (Prozentsatz des "
            "externen Standardprodukts des Netzbetreibers oder fester Tarif). Er darf gemäss Gesetz den "
            "regulären Stromtarif des Netzbetreibers (inkl. Netznutzung, Abgaben und Zuschläge) nicht "
            "überschreiten. Der Anteil Strom, der nicht lokal gedeckt werden kann, wird weiterhin zum "
            "regulären Tarif vom Netzbetreiber bezogen."
        ),
        "duration_title": "Vertragsdauer und Kündigung",
        "duration_text": (
            "Dieser Vertrag wird auf unbestimmte Dauer abgeschlossen und tritt mit der Unterschrift beider "
            "Parteien in Kraft. Ein Eigentümer kann, soweit nach anwendbarem Recht zulässig, diesen Vertrag schriftlich "
            "mit einer Frist von zwei Monaten auf Ende einer Abrechnungsperiode kündigen, vorbehaltlich des vom "
            "Netzbetreiber verlangten "
            "Mutationsverfahrens. Für Mieter und Pächter richten sich Teilnahme, Austritt und weitere "
            "Versorgung nach dem zwingenden schweizerischen Mietrecht, dem Mietvertrag und den anwendbaren "
            "energierrechtlichen Vorgaben. Soweit ein Mieter zum Austritt berechtigt ist, gelten die gesetzlich "
            "vorgeschriebene Frist und das vorgeschriebene Verfahren. Ein Austritt wird erst wirksam, wenn er "
            "in der vom Netzbetreiber verlangten Mess- und Versorgungslösung umgesetzt ist."
        ),
        "jurisdiction_title": "Kommunikation, Streitbeilegung und Schlussbestimmungen",
        "jurisdiction_text": (
            "Dieser Vertrag untersteht schweizerischem Recht. Gerichtsstand ist der Sitz des vZEV "
            "bzw. der Wohnort des vZEV-Verantwortlichen. Änderungen bedürfen der Schriftform. Sollte eine "
            "Bestimmung unwirksam sein, bleibt der Vertrag im Übrigen wirksam; die Parteien ersetzen die "
            "unwirksame Bestimmung durch eine wirksame, die dem Zweck am nächsten kommt.\n\n"
            "Ändern sich die gesetzlichen Vorgaben oder die Anforderungen des Netzbetreibers so, dass "
            "der vZEV nicht weitergeführt werden kann, kann der vZEV-Verantwortliche ihn mit "
            "angemessener Frist auflösen; die Parteien werden ab dann ausschliesslich zum externen "
            "Standardtarif versorgt."
        ),
        "definitions_title": "Begriffe",
        "definitions_items": [
            "«vZEV»: Virtueller Zusammenschluss zum Eigenverbrauch gemäss Art. 16–18 EnG, Art. 14–18 EnV "
            "sowie Art. 17a–17c EnG.",
            "«vZEV-Verantwortlicher»: Die Partei, die den vZEV gegenüber dem Netzbetreiber anmeldet, verwaltet "
            "und die interne Abrechnung organisiert.",
            "«Teilnehmer»: Jede Partei, die am vZEV teilnimmt und lokale Energie bezieht (Eigentümer oder Mieter).",
            "«Netzbetreiber»: Das Elektrizitätsversorgungsunternehmen, an dessen Netz der vZEV angeschlossen ist.",
            "«Produktionsanlage»: Die Erzeugungsanlage (insb. Photovoltaik), deren lokale Produktion den "
            "Teilnehmern zugeordnet wird.",
            "«Messpunkt»: Der Smart Meter mit 33-stelliger, mit «CH» beginnender Nummer, der Verbrauch bzw. "
            "Produktion erfasst.",
            "«Externer Standardtarif»: Der reguläre Tarif des Netzbetreibers für Energie, Netznutzung und "
            "Abgaben ohne vZEV.",
        ],
        "manager_title": "Organisation und Aufgaben des vZEV-Verantwortlichen",
        "manager_text": (
            "Der vZEV-Verantwortliche vertritt den vZEV gegenüber dem Netzbetreiber und den Behörden, besorgt "
            "die Anmeldung und alle laufenden Mutationen und stellt die technischen und rechtlichen "
            "Voraussetzungen (insb. Smart Meter und erforderliche Produktionsleistung) sicher. Operative "
            "Aufgaben erledigt er in eigener Kompetenz; die Aufnahme neuer Teilnehmer und Änderungen "
            "dieses Vertrags bedürfen der Zustimmung aller Teilnehmer. Der vZEV-Verantwortliche "
            "informiert die Teilnehmer mindestens einmal jährlich über Tarife, Produktion und "
            "Zuordnung."
        ),
        "manager_duties": [
            "rechtzeitige Erstellung und Zustellung der internen Stromrechnungen;",
            "Führung des Teilnehmerverzeichnisses und Pflege der Tarife;",
            "Organisation des Zugangs zu den Smart-Meter-Daten;",
            "Weitergabe der externen Netzbetreiber-Rechnung und interne Kostenverteilung;",
            "Information der Teilnehmer über regulatorische Änderungen, die den vZEV betreffen.",
        ],
        # Bold clause lead-ins are separate keys: the markup lives in the
        # template (<strong>{{ tr.…_lead }}</strong>), so translation values
        # stay plain text and are never rendered |safe.
        "clause_tariff_rule_lead": "Tarifregel.",
        "clause_tariff_cap_lead": "Tarifobergrenze.",
        "clause_tariff_adjustment_lead": "Mitteilung und Kündigung.",
        "clause_billing_lead": "Rechnung und Verzug.",

        "clause_tariff_rule_pct": (
            "Der Preis für lokal erzeugten und im vZEV verbrauchten Strom "
            "beträgt {pct} % des für den Teilnehmer massgebenden externen Standardprodukts des "
            "Netzbetreibers (Energie, Netznutzung, Abgaben und Zuschläge; ohne einmalige Kosten und ohne "
            "Mehrwertsteuer, sofern nicht ausdrücklich anders vereinbart). Der ausgewiesene Tarif gilt ausschliesslich für "
            "dem Teilnehmer zugeordnete lokal erzeugte Energie; Netzstrom, Netznutzung, Abgaben, Messkosten und "
            "vereinbarte Verwaltungskosten werden gemäss den Zuordnungsregeln separat verrechnet. Der Tarif passt "
            "sich automatisch "
            "an, wenn der Netzbetreiber seine Preise ändert; der vZEV-Verantwortliche teilt den Teilnehmern "
            "den jeweils geltenden Tarifwert mit jeder Rechnung oder mindestens jährlich mit."
        ),
        "clause_tariff_rule_flat": (
            "Der Tarif für lokal erzeugten und im vZEV verbrauchten Strom ist "
            "ein fester Tarif, wie er in der Tariftabelle dieser Ziffer ausgewiesen ist. Der ausgewiesene Tarif gilt "
            "ausschliesslich für dem Teilnehmer zugeordnete lokal erzeugte Energie; Netzstrom, Netznutzung, "
            "Abgaben, Messkosten und vereinbarte Verwaltungskosten werden gemäss den Zuordnungsregeln separat "
            "verrechnet. Er wird jährlich "
            "überprüft und bei Änderungen der Netzbetreiber-Preise angepasst; neue Tarife werden den "
            "Teilnehmern mindestens einen Monat im Voraus mitgeteilt."
        ),
        "clause_tariff_cap": (
            "Der Tarif für lokale Energie darf den externen Standardtarif des "
            "Netzbetreibers für die gleiche Energiemenge nicht übersteigen. Für Mieter gelten die anwendbaren "
            "miet- und energierechtlichen Preis- und Kostenregeln. Wird die gesetzliche vereinfachte Methode mit "
            "80 % angewendet, gilt dieser Prozentsatz für die gesetzlich definierte Kostenbasis; andernfalls "
            "sind die effektive Kostenrechnung und die anwendbare Obergrenze zu dokumentieren. Der ausgewiesene "
            "Tarif gilt ausschliesslich für dem Teilnehmer zugeordnete lokal erzeugte Energie; Netzstrom, "
            "Netznutzung, Abgaben, Messkosten und vereinbarte Verwaltungskosten werden gemäss den "
            "Zuordnungsregeln separat verrechnet. Die Tarifregel in dieser Ziffer legt fest, ob die "
            "Mehrwertsteuer enthalten ist; zwingendes Recht geht vor."
        ),
        "clause_tariff_adjustment": (
            "Tarifänderungen werden den Teilnehmern mindestens einen Monat vor ihrem "
            "Inkrafttreten mitgeteilt. Rechte zur Kündigung oder zum Austritt infolge einer Tarifänderung "
            "richten sich nach Ziffer 10, dem zwingenden Recht und – soweit erforderlich – dem vom "
            "Netzbetreiber verlangten Verfahren."
        ),
        "clause_billing": (
            "Der vZEV-Verantwortliche begleicht die Rechnung des Netzbetreibers und verteilt die Kosten intern "
            "gemäss den vereinbarten Zuordnungsregeln. Rechnungen sind innerhalb der vereinbarten Frist zu "
            "bezahlen; nach Mahnung werden ein Verzugszins von 5 % p.a. sowie angemessene Mahnspesen fällig. "
            "Bei wiederholt unbezahlten Rechnungen kann der vZEV-Verantwortliche nach Mahnung und unter "
            "Einhaltung des zwingenden Rechts die Teilnahme gemäss Ziffer 10 kündigen. Eine daraus folgende "
            "Änderung der Mess- oder Versorgungslösung richtet sich nach dem anwendbaren Recht und den "
            "Anforderungen des Netzbetreibers."
        ),
        "metering_title": "Messung und Zuordnung",
        "metering_text": (
            "Alle Parteien nutzen Smart Meter gemäss den Vorgaben des Netzbetreibers. Die "
            "Zuordnung erfolgt pro Messintervall: Lokale Energie ist derjenige Teil der Produktion, der "
            "im Intervall verbraucht und im Verhältnis der gleichzeitigen Verbräuche verteilt wird; nicht "
            "beanspruchte, ins Netz eingespeiste Produktion wird den Produktionsanlagen anteilsmässig "
            "zugeordnet, und die Einspeisevergütung steht der Eigentümerschaft der Produktionsanlage zu. "
            "Grundlage der internen Abrechnung sind die pro Abrechnungsperiode gemessenen kWh-Werte; "
            "fehlende oder unplausible Messdaten werden vom vZEV-Verantwortlichen vorläufig auf Basis der "
            "Vorperioden geschätzt. Sobald validierte Messdaten vorliegen, ersetzen sie die Schätzung; "
            "Differenzen werden mit der nächsten Rechnung gutgeschrieben oder belastet."
        ),
        "liability_title": "Haftung und Regress",
        "liability_text": (
            "Gegenüber dem Netzbetreiber haften alle Teilnehmer für Netz- und Bezugskosten solidarisch "
            "(Art. 17 EnG); im Innenverhältnis trägt jede Partei ihren Anteil. Deckt eine Partei ihren Anteil "
            "nicht, schuldet sie den übrigen Parteien und dem vZEV-Verantwortlichen Ersatz. Es besteht kein "
            "Anspruch auf eine minimale Menge lokaler Energie; bei Ausfall oder Minderproduktion der Anlage "
            "wird die Differenz zum externen Standardtarif gedeckt. Für Ereignisse ausserhalb des "
            "Einflussbereichs des vZEV-Verantwortlichen (Netzstörungen, behördliche Eingriffe, Systemausfälle) "
            "besteht keine Haftung. Die Grundversorgung durch den Netzbetreiber bleibt jederzeit "
            "gewährleistet."
        ),
        "membership_title": "Beitritt, Austritt und Mutationen",
        "membership_text": (
            "Neue Parteien können nur beitreten, wenn die gesetzlichen Voraussetzungen für den Zusammenschluss "
            "zum Eigenverbrauch am Ort der Produktion erfüllt sind. Insbesondere müssen die Nutzung von "
            "Anschlussleitungen und der lokalen elektrischen Infrastruktur am massgeblichen Netzanschlusspunkt "
            "zulässig sein; die technische Beurteilung und das Anmelde- und Mutationsverfahren des Netzbetreibers "
            "sind massgebend. Jede Partei behält ihren eigenen Netzanschluss. Der Beitritt erfordert die "
            "schriftliche Unterzeichnung dieses Vertrags. Mutationen (Wegzug, Hausverkauf u. Ä.) sind dem "
            "vZEV-Verantwortlichen spätestens 14 Tage nach Bekanntwerden zu melden. Bei Eigentumswechsel tritt "
            "die neue Eigentümerschaft mit schriftlicher Zustimmung in den Vertrag ein; andernfalls wird sie "
            "ausschliesslich zum externen Standardtarif versorgt. Beim Austritt einer Partei wird deren Anteil "
            "an Produktion und Kosten anteilsmässig auf die verbleibenden Teilnehmer verteilt."
        ),
        "privacy_title": "Datenschutz",
        "privacy_text": (
            "Der vZEV-Verantwortliche ist Verantwortlicher im Sinne des Datenschutzgesetzes (DSG, SR 235.1). Er "
            "bearbeitet Kontakt- und Messpunktdaten sowie Verbrauchs- und Produktionsprofile ausschliesslich "
            "zur Zuordnung, Abrechnung und Verwaltung des vZEV. Daten werden nur an den Netzbetreiber und an "
            "beigezogene Abrechnungsdienstleister übermittelt, soweit erforderlich. Die Daten werden für die "
            "Dauer der Teilnahme und darüber hinaus nur so lange aufbewahrt, wie es gesetzliche "
            "Aufbewahrungspflichten verlangen; nicht mehr benötigte Daten werden gelöscht. Die "
            "Parteien haben das Recht auf Auskunft, Berichtigung und, soweit rechtlich möglich, Löschung "
            "ihrer Daten."
        ),
        "privacy_short": (
            "Der vZEV-Verantwortliche bearbeitet Kontakt- und Messdaten ausschliesslich für Zuordnung, "
            "Abrechnung und Administration des vZEV; eine Weitergabe an Netzbetreiber und "
            "Abrechnungsdienstleister erfolgt nur, soweit erforderlich. Die vollständige "
            "Datenschutzerklärung findet sich in Anhang B."
        ),
        "privacy_controller_title": "Verantwortlicher",
        "privacy_controller_text": (
            "Verantwortlicher im Sinne des Datenschutzgesetzes (DSG, SR 235.1) ist der in Ziffer 1 "
            "bezeichnete vZEV-Verantwortliche:"
        ),
        "privacy_purposes_title": "Bearbeitete Daten und Zwecke",
        "privacy_purposes_items": [
            "Kontakt- und Identifikationsdaten (Name, Adresse, E-Mail, Telefon) für die Vertragsabwicklung und Kommunikation;",
            "Messpunkt- und Zählerdaten zur Zuordnung von Verbrauch und Produktion;",
            "Verbrauchs- und Produktionsprofile zur Abrechnung und Verwaltung des vZEV.",
        ],
        "privacy_recipients_title": "Empfänger",
        "privacy_recipients_text": (
            "Daten werden nur an den Netzbetreiber und an beigezogene Abrechnungsdienstleister "
            "übermittelt, soweit dies für den Betrieb des vZEV erforderlich ist. Eine Weitergabe "
            "zu anderen Zwecken erfolgt nicht; eine Übermittlung ins Ausland erfolgt nur, soweit "
            "gesetzlich zulässig und erforderlich."
        ),
        "privacy_retention_title": "Aufbewahrungsdauer",
        "privacy_retention_col_data": "Datenkategorie",
        "privacy_retention_col_period": "Aufbewahrungsdauer",
        "privacy_retention_categories": [
            "Abrechnungsunterlagen und Verträge",
            "Aggregierte Messdaten",
            "Hochauflösende Messdaten",
            "Kontakt- und Vertragsdaten",
        ],
        "privacy_retention_periods": [
            "10 Jahre (gesetzliche Aufbewahrungspflicht)",
            "10 Jahre (Abrechnungsgrundlage)",
            "Gelöscht, sobald für die Abrechnung nicht mehr erforderlich; gesetzliche Fristen bleiben vorbehalten",
            "Dauer der Teilnahme, danach gemäss gesetzlichen Fristen",
        ],
        "privacy_rights_title": "Rechte der Teilnehmer",
        "privacy_rights_items": [
            "Auskunft über die bearbeiteten eigenen Daten;",
            "Berichtigung unrichtiger Daten;",
            "Löschung, soweit rechtlich möglich und keine Aufbewahrungspflichten entgegenstehen;",
            "Einschränkung der Bearbeitung und Datenübertragbarkeit nach Massgabe des DSG;",
            "Beschwerde beim Eidgenössischen Datenschutz- und Öffentlichkeitsbeauftragten (EDÖB).",
        ],
        "appendix_b_title": "Anhang B",
        "appendix_b_subtitle": "Datenschutzerklärung – Bestandteil des Vertrags",
        "communication_text": (
            "Mitteilungen per E-Mail an die zuletzt bekannte Adresse gelten drei Tage nach Versand als "
            "zugestellt. Bei Streitigkeiten suchen die Parteien zunächst eine einvernehmliche Lösung; bleibt "
            "diese aus, entscheidet das zuständige Gericht."
        ),
        "info_privacy_title": "Datenschutz",
        "info_privacy_text": (
            "Wie der vZEV-Verantwortliche Personen- und Messdaten bearbeitet, regelt die verbindliche "
            "Datenschutzerklärung in Anhang B dieses Vertrags."
        ),
    },
    "fr": {
        "contract_title": "Contrat de participation vZEV",
        "parties_title": "Parties contractantes",
        "participant_label": "Participant au vZEV (ci-après «participant vZEV»)",
        "owner_label": "Responsable du vZEV (ci-après «responsable vZEV»)",

        "field_address": "Adresse, Lieu",
        "field_phone": "Téléphone",
        "field_email": "E-mail",
        "field_meter": "Numéro de point de mesure",

        "meter_none": "Aucun point de mesure attribué",

        "field_meter_pv": "Numéro de point de mesure (PV / injection)",
        "subject_title": "Objet et champ d'application",
        "subject_text": (
            "Le présent contrat régit la participation au vZEV ainsi que les relations internes entre les "
            "participants et le responsable vZEV, sur la base de la législation suisse applicable en "
            "matière de communautés de consommation propre (EnG, EnV, acte de portée générale).\n\n"
            "Envers le gestionnaire de réseau, le vZEV se présente comme un client unique ; le présent contrat "
            "règle exclusivement les droits et obligations internes, la répartition de l'énergie locale et la "
            "facturation de celle-ci.\n\n"
            "Le présent contrat est conclu bilatéralement entre le responsable vZEV et chaque "
            "participant ; les contrats identiques de tous les participants forment ensemble le "
            "règlement interne du vZEV."
        ),
        "agreements_title": "Conventions",
        "local_tariff_label": "Votre tarif d'énergie solaire locale",
        "local_tariff_unit": "Centimes / kWh",
        "local_tariff_note": "Autres règles tarifaires",
        "local_tariff_note_placeholder": "",
        "tariff_pct_of": "= {pct} % du tarif standard du gestionnaire de réseau",
        "tariff_valid_open": "dès le {date}",
        "tariff_valid_label": "Validité",
        "reference_product_label": "Produit de référence",
        "billing_interval_label": "Intervalle de facturation",
        "payment_terms_label": "Conditions de paiement",
        "payment_terms_unit_sg": "jour à compter de la date de facturation",
        "payment_terms_unit_pl": "jours à compter de la date de facturation",
        "vat_label": "TVA",
        "vat_not_required": "Non assujetti",
        "vat_required": "Assujetti à la TVA",
        "additional_label": "Conventions supplémentaires",
        "additional_placeholder": "",
        "signatures_title": "Signatures",
        "sig_intro": (
            "Par leur signature, les parties contractantes confirment avoir lu et compris le contenu du présent "
            "contrat et l'acceptent."
        ),
        "sig_participant": "Participant vZEV",
        "sig_owner": "Responsable vZEV",
        "sig_place_date": "Lieu, Date",

        "sig_signature": "Signature",
        "page_label": "Page",
        "page_of": "de",
        "billing_intervals": {
            "monthly": "Mensuel",
            "quarterly": "Trimestriel",
            "semi_annual": "Semestriel",
            "annual": "Annuel",
        },
        "tariff_ht": "HT (tarif plein)",
        "tariff_nt": "NT (tarif creux)",
        "tariff_flat": "Tarif unique",
        "tariff_pct_prefix": "% du tarif réseau",
        "tariff_rp_unit": "cts/kWh",
        "tariff_none": "—",
        "tariff_col_name": "Tarif",
        "tariff_col_price": "Prix (cts/kWh)",
        "tariff_col_calc": "Calcul",

        "contract_date_label": "Date d'émission",
        "participation_start_label": "Début de participation",
        "appendix_title": "Annexe A – Informations générales (sans caractère contraignant ; le contrat prévaut)",
        "meter_hint": "Le numéro de point de mesure figure sur la facture d'électricité. Il comporte 33 caractères et commence par CH.",

        "info_subtitle": "Informations générales pour les regroupements pour la consommation propre",
        "precedence_note": (
            "La présente annexe contient des informations générales sans caractère contraignant et ne remplace "
            "pas un conseil juridique. En cas de divergence, les clauses numérotées du contrat priment sur les "
            "informations de la présente annexe. L'annexe B est contraignante pour le traitement des données "
            "personnelles."
        ),
        "info_zev_title": "Qu'est-ce qu'un RCP ?",
        "info_zev_text": (
            "Un regroupement pour la consommation propre (RCP) permet aux propriétaires fonciers d'utiliser "
            "conjointement l'électricité produite localement (p.\u202fex. à partir d'installations solaires). "
            "Les participants se trouvent au même point de raccordement au réseau. Le RCP se présente auprès du "
            "gestionnaire de réseau comme un client unique et organise la facturation interne de manière autonome."
        ),
        "info_vzev_title": "Qu'est-ce qu'un RCP virtuel (vRCP) ?",
        "info_vzev_text": (
            "Un RCP virtuel (vRCP) étend le modèle RCP : les participants ne doivent plus se trouver au même "
            "point de raccordement. La participation n'est toutefois admissible que si les conditions légales "
            "du regroupement pour la consommation propre au lieu de production sont remplies. En particulier, "
            "l'utilisation des lignes de raccordement et de l'infrastructure électrique locale au point de "
            "raccordement concerné doit être permise par le droit applicable. L'évaluation technique et la "
            "procédure d'annonce et de mutation du gestionnaire de réseau sont déterminantes. Chaque participant "
            "conserve son propre raccordement. L'attribution de la consommation propre s'effectue virtuellement "
            "sur la base des données de compteurs intelligents."
        ),
        "info_legal_title": "Bases légales",
        "info_legal_items": [
            "Loi sur l'énergie (LEne, RS 730.0), art. 16–18 — Réglementation de la consommation propre et du RCP",
            "Ordonnance sur l'énergie (OEne, RS 730.01), art. 14–18 — Dispositions d'exécution",
            "Loi sur l'approvisionnement en électricité (LApEl, RS 734.7) — Accès au réseau et approvisionnement de base",
            "Loi fédérale relative à un approvisionnement en électricité sûr reposant sur des énergies renouvelables "
            "(acte modificateur unique) — Extension au vRCP (art. 17a–17c LEne)",
        ],
        "info_rights_title": "Droits et obligations des participants",
        "info_rights_items": [
            "Le tarif local d'électricité ne doit pas dépasser le tarif réseau ordinaire du gestionnaire de réseau.",
            "La sortie et la résiliation sont régies par le ch. 10 du présent contrat et par le droit impératif, "
            "notamment le droit du bail lorsqu'il est applicable.",
            "Le responsable du vRCP établit les factures d'électricité internes et administre le regroupement.",
            "Les changements (déménagement, changement de propriétaire) doivent être signalés sans délai au responsable.",
            "L'approvisionnement de base par le gestionnaire de réseau reste garanti en tout temps pour tous les participants.",
        ],
        "info_liability_title": "Responsabilité solidaire",
        "info_liability_text": (
            "Tous les participants d'un RCP ou vRCP sont solidairement responsables envers le gestionnaire de "
            "réseau pour les coûts de réseau et l'électricité achetée (art. 17 al. 2 LEne). Cela signifie que "
            "si un participant ne peut pas payer sa facture d'électricité, les autres participants peuvent être "
            "tenus de régler le montant dû. La répartition interne des coûts est gérée par le responsable du "
            "vRCP par le biais de la facturation d'électricité."
        ),
        "info_tariff_title": "Dispositions tarifaires",
        "info_tariff_text": (
            "Le tarif de l'électricité produite localement suit la règle tarifaire du ch. 5 (pourcentage du "
            "produit standard externe du gestionnaire de réseau ou tarif fixe). Conformément à la loi, il ne "
            "doit pas dépasser le tarif d'électricité ordinaire du gestionnaire de réseau (y compris "
            "utilisation du réseau, taxes et suppléments). La part d'électricité qui ne peut pas être "
            "couverte localement continue d'être achetée au tarif ordinaire auprès du gestionnaire de réseau."
        ),
        "duration_title": "Durée du contrat et résiliation",
        "duration_text": (
            "Le présent contrat est conclu pour une durée indéterminée et entre en vigueur dès la signature "
            "des deux parties. Un propriétaire peut, lorsque le droit applicable le permet, résilier le présent contrat "
            "par écrit avec un préavis de deux mois pour la fin d'une période de facturation, sous réserve de la "
            "procédure de mutation "
            "requise par le gestionnaire de réseau. Pour les locataires et fermiers, la participation, la sortie "
            "et la poursuite de l'approvisionnement sont régies par le droit suisse impératif du bail, le bail "
            "et les exigences applicables du droit de l'énergie. Lorsqu'un locataire est autorisé à sortir, le "
            "délai et la procédure prévus par la loi s'appliquent. Toute sortie ne prend effet qu'une fois mise "
            "en œuvre dans la solution de mesure et d'approvisionnement requise par le gestionnaire de réseau."
        ),
        "jurisdiction_title": "Communication, litiges et dispositions finales",
        "jurisdiction_text": (
            "Le présent contrat est soumis au droit suisse. Le for juridique est le siège du vZEV "
            "ou le domicile du responsable vZEV. Toute modification requiert la forme écrite. Si une "
            "disposition est nulle, le contrat demeure valable pour le surplus ; les parties remplacent la "
            "disposition nulle par une disposition valable aussi proche que possible de son objet.\n\n"
            "Si les exigences légales ou celles du gestionnaire de réseau évoluent de telle sorte que "
            "le vZEV ne peut plus être maintenu, le responsable vZEV peut le dissoudre avec un délai "
            "approprié ; les parties sont alors alimentées exclusivement au tarif externe standard."
        ),
        "definitions_title": "Définitions",
        "definitions_items": [
            "« vZEV » : regroupement virtuel pour la consommation propre au sens des art. 16–18 EnG, "
            "14–18 EnV et 17a–17c EnG.",
            "« Responsable vZEV » : la partie qui annonce le vZEV au gestionnaire de réseau, l'administre et "
            "organise la facturation interne.",
            "« Participant » : toute partie qui participe au vZEV et consomme de l'énergie locale "
            "(propriétaire ou locataire).",
            "« Gestionnaire de réseau » : l'entreprise d'approvisionnement en électricité au réseau de "
            "laquelle le vZEV est raccordé.",
            "« Installation de production » : l'installation (notamment photovoltaïque) dont la production "
            "locale est attribuée aux participants.",
            "« Point de mesure » : compteur intelligent dont le numéro de 33 caractères commence par « CH » "
            "et qui saisit la consommation ou la production.",
            "« Tarif externe standard » : tarif ordinaire du gestionnaire de réseau pour l'énergie, "
            "l'utilisation du réseau et les taxes, sans vZEV.",
        ],
        "manager_title": "Organisation et tâches du responsable vZEV",
        "manager_text": (
            "Le responsable vZEV représente le vZEV envers le gestionnaire de réseau et les autorités, "
            "procède à l'annonce et à toutes les mutations courantes et garantit les conditions techniques et "
            "juridiques (notamment compteurs intelligents et puissance de production requise). Il accomplit "
            "les tâches opérationnelles de sa propre compétence ; l'admission de nouveaux participants et "
            "toute modification du présent contrat requièrent l'accord de tous les participants. Le "
            "responsable vZEV informe les participants au moins une fois par an sur les tarifs, la "
            "production et l'attribution."
        ),
        "manager_duties": [
            "établissement et envoi ponctuels des factures d'électricité internes ;",
            "tenue du registre des participants et gestion des tarifs ;",
            "organisation de l'accès aux données des compteurs intelligents ;",
            "transmission de la facture du gestionnaire de réseau et répartition interne des coûts ;",
            "information des participants sur les modifications réglementaires affectant le vZEV.",
        ],
        "clause_tariff_rule_lead": "Règle tarifaire.",
        "clause_tariff_cap_lead": "Plafond tarifaire.",
        "clause_tariff_adjustment_lead": "Communication et résiliation.",
        "clause_billing_lead": "Facturation et demeure.",

        "clause_tariff_rule_pct": (
            "Le prix de l'électricité produite localement et consommée "
            "au sein du vZEV correspond à {pct} % du produit standard externe applicable du gestionnaire "
            "de réseau (énergie, utilisation du réseau, taxes et suppléments ; hors frais uniques et hors "
            "TVA, sauf convention contraire expresse). Le tarif indiqué s'applique exclusivement à l'énergie produite "
            "localement et attribuée au participant ; l'électricité du réseau, l'utilisation du réseau, les taxes, "
            "les coûts de mesure et les frais d'administration convenus sont facturés séparément selon les règles "
            "d'attribution. Le tarif s'adapte automatiquement lorsque le "
            "gestionnaire de réseau modifie ses prix ; le responsable vZEV communique aux participants la "
            "valeur tarifaire en vigueur avec chaque facture ou au moins une fois par année."
        ),
        "clause_tariff_rule_flat": (
            "Le tarif de l'électricité produite localement et consommée "
            "au sein du vZEV est un tarif fixe, tel qu'il figure dans le tableau tarifaire de la présente "
            "section. Le tarif indiqué s'applique exclusivement à l'énergie produite localement et attribuée au participant ; l'électricité du réseau, l'utilisation du réseau, les taxes, les coûts de mesure et les frais d'administration convenus sont facturés séparément selon les règles d'attribution. Il est examiné chaque année et adapté en cas de modification des prix du gestionnaire "
            "de réseau ; les nouveaux tarifs sont communiqués aux participants au moins un mois à l'avance."
        ),
        "clause_tariff_cap": (
            "Le tarif de l'énergie locale ne doit pas dépasser le tarif externe standard "
            "du gestionnaire de réseau pour la même quantité d'énergie. Pour les locataires, les règles "
            "applicables du droit du bail et du droit de l'énergie en matière de prix et de coûts doivent être "
            "respectées. Lorsque la méthode simplifiée légale avec 80 % est appliquée, ce pourcentage porte sur "
            "la base de coûts définie par la loi ; dans les autres cas, le calcul effectif des coûts et le "
            "plafond applicable doivent être documentés. Le tarif indiqué s'applique exclusivement à l'énergie "
            "produite localement et attribuée au participant ; l'électricité du réseau, l'utilisation du réseau, "
            "les taxes, les coûts de mesure et les frais d'administration convenus sont facturés séparément selon "
            "les règles d'attribution. La règle tarifaire de la présente section précise si la TVA est comprise ; "
            "le droit impératif prévaut."
        ),
        "clause_tariff_adjustment": (
            "Les modifications tarifaires sont communiquées aux participants au moins un mois "
            "avant leur entrée en vigueur. Les droits de résiliation ou de sortie à la suite d'une modification "
            "tarifaire sont régis par le ch. 10, le droit impératif et, si nécessaire, la procédure requise par "
            "le gestionnaire de réseau."
        ),
        "clause_billing": (
            "Le responsable vZEV règle la facture du gestionnaire de réseau et répartit les coûts en interne "
            "selon les règles d'attribution convenues. Les factures sont payables dans le délai convenu ; "
            "après mise en demeure, un intérêt moratoire de 5 % l'an et des frais de rappel raisonnables sont "
            "exigibles. En cas de factures répétitivement impayées, le responsable vZEV peut, après rappel et "
            "sous réserve du droit impératif, résilier la participation conformément au ch. 10. Toute "
            "modification qui en découle de la solution de mesure ou d'approvisionnement est régie par le droit "
            "applicable et les exigences du gestionnaire de réseau."
        ),
        "metering_title": "Mesure et attribution",
        "metering_text": (
            "Toutes les parties utilisent des compteurs intelligents conformément aux prescriptions du "
            "gestionnaire de réseau. L'attribution a lieu par intervalle de mesure : l'énergie locale "
            "est la part de la production consommée pendant l'intervalle, répartie proportionnellement aux "
            "consommations simultanées ; la production non utilisée injectée dans le réseau est attribuée au "
            "prorata aux installations de production, et la rétribution de l'injection revient aux propriétaires "
            "de l'installation. La facturation interne se fonde sur les valeurs kWh mesurées par période ; les "
            "données manquantes ou invraisemblables sont provisoirement estimées par le responsable vZEV sur la "
            "base des périodes précédentes. Dès que des données validées sont disponibles, elles remplacent "
            "l'estimation ; les différences sont créditées ou débitées sur la facture suivante."
        ),
        "liability_title": "Responsabilité et recours",
        "liability_text": (
            "Envers le gestionnaire de réseau, tous les participants répondent solidairement des coûts de "
            "réseau et d'approvisionnement (art. 17 EnG) ; dans les relations internes, chaque partie "
            "supporte sa part. Si une partie ne couvre pas sa part, elle en doit réparation aux autres "
            "parties et au responsable vZEV. Il n'existe aucun droit à une quantité minimale d'énergie "
            "locale ; en cas de panne ou de production réduite, la différence est couverte au tarif externe "
            "standard. Aucune responsabilité n'est retenue pour des événements échappant au contrôle du "
            "responsable vZEV (perturbations du réseau, mesures officielles, pannes de système). "
            "L'approvisionnement de base par le gestionnaire de réseau reste garanti en tout temps."
        ),
        "membership_title": "Adhésion, sortie et mutations",
        "membership_text": (
            "De nouvelles parties ne peuvent adhérer que si les conditions légales du regroupement pour la "
            "consommation propre au lieu de production sont remplies. En particulier, l'utilisation des lignes "
            "de raccordement et de l'infrastructure électrique locale au point de raccordement concerné doit être "
            "permise ; l'évaluation technique et la procédure d'annonce et de mutation du gestionnaire de réseau "
            "sont déterminantes. Chaque partie conserve son propre raccordement au réseau. L'adhésion requiert "
            "la signature du présent contrat par écrit. Les mutations (déménagement, vente de la maison, etc.) "
            "sont annoncées au responsable vZEV au plus tard 14 jours après en avoir eu connaissance. En cas de "
            "changement de propriétaire, le nouveau propriétaire adhère au contrat avec son accord écrit ; à "
            "défaut, il est alimenté exclusivement au tarif externe standard. En cas de sortie d'une partie, sa "
            "part de production et de coûts est répartie au prorata entre les participants restants."
        ),
        "privacy_title": "Protection des données",
        "privacy_text": (
            "Le responsable vZEV est responsable du traitement au sens de la loi sur la protection des données "
            "(LPD, RS 235.1). Il traite les données de contact et les numéros de point de mesure ainsi que "
            "les profils de consommation et de production exclusivement pour l'attribution, la facturation et "
            "l'administration du vZEV. Les données ne sont transmises au gestionnaire de réseau et aux "
            "prestataires de facturation que dans la mesure nécessaire. Elles sont conservées pendant la "
            "durée de la participation et, au-delà, uniquement aussi longtemps que les obligations légales "
            "de conservation l'exigent ; les données qui ne sont plus nécessaires sont supprimées. "
            "Les parties ont droit à l'accès, à la rectification et, lorsque la loi le permet, à la "
            "suppression de leurs données."
        ),
        "privacy_short": (
            "Le responsable vZEV traite les données de contact et de mesure exclusivement aux fins "
            "d'attribution, de facturation et d'administration du vZEV ; elles ne sont transmises au "
            "gestionnaire de réseau et aux prestataires de facturation que dans la mesure nécessaire. La "
            "notice complète sur la protection des données figure à l'annexe B."
        ),
        "privacy_controller_title": "Responsable du traitement",
        "privacy_controller_text": (
            "Le responsable du traitement au sens de la loi sur la protection des données "
            "(LPD, RS 235.1) est le responsable vZEV désigné au ch. 1 :"
        ),
        "privacy_purposes_title": "Données traitées et finalités",
        "privacy_purposes_items": [
            "Données de contact et d'identification (nom, adresse, e-mail, téléphone) pour l'exécution du contrat et la communication ;",
            "Numéros de point de mesure et données des compteurs pour l'attribution de la consommation et de la production ;",
            "Profils de consommation et de production pour la facturation et l'administration du vZEV.",
        ],
        "privacy_recipients_title": "Destinataires",
        "privacy_recipients_text": (
            "Les données ne sont transmises au gestionnaire de réseau et aux prestataires de "
            "facturation que dans la mesure nécessaire au fonctionnement du vZEV. Aucune "
            "transmission à d'autres fins n'est effectuée ; une transmission à l'étranger "
            "n'intervient que si elle est légalement admissible et nécessaire."
        ),
        "privacy_retention_title": "Durée de conservation",
        "privacy_retention_col_data": "Catégorie de données",
        "privacy_retention_col_period": "Durée de conservation",
        "privacy_retention_categories": [
            "Pièces de facturation et contrats",
            "Données de mesure agrégées",
            "Données de mesure haute résolution",
            "Données de contact et contractuelles",
        ],
        "privacy_retention_periods": [
            "10 ans (obligation légale de conservation)",
            "10 ans (base de facturation)",
            "Supprimées dès qu'elles ne sont plus nécessaires à la facturation ; les délais légaux restent réservés",
            "Durée de la participation, puis selon les délais légaux",
        ],
        "privacy_rights_title": "Droits des participants",
        "privacy_rights_items": [
            "Accès aux données personnelles traitées ;",
            "Rectification des données inexactes ;",
            "Effacement dans la mesure où il est légalement possible et qu'aucune obligation de conservation ne s'y oppose ;",
            "Restriction du traitement et portabilité des données selon la LPD ;",
            "Plainte auprès du Préposé fédéral à la protection des données et à la transparence (PFPDT).",
        ],
        "appendix_b_title": "Annexe B",
        "appendix_b_subtitle": "Notice sur la protection des données – partie intégrante du contrat",
        "communication_text": (
            "Les communications par e-mail à la dernière adresse connue sont réputées reçues trois jours "
            "après l'envoi. En cas de litige, les parties recherchent d'abord une solution à l'amiable ; à "
            "défaut, le tribunal compétent statue."
        ),
        "info_privacy_title": "Protection des données",
        "info_privacy_text": (
            "Le traitement des données personnelles et de mesure par le responsable vZEV est régi par la "
            "notice contraignante sur la protection des données figurant à l'annexe B du présent contrat."
        ),
    },
    "it": {
        "contract_title": "Contratto di partecipazione ZEV virtuale",
        "parties_title": "Parti contraenti",
        "participant_label": "Partecipante al vZEV (di seguito «partecipante vZEV»)",
        "owner_label": "Responsabile del vZEV (di seguito «responsabile vZEV»)",

        "field_address": "Indirizzo, Luogo",
        "field_phone": "Telefono",
        "field_email": "E-mail",
        "field_meter": "Numero punto di misura",

        "meter_none": "Nessun punto di misura assegnato",

        "field_meter_pv": "Numero punto di misura (FV / immissione)",
        "subject_title": "Oggetto e campo di applicazione",
        "subject_text": (
            "Il presente contratto disciplina la partecipazione al vZEV e il rapporto interno tra i "
            "partecipanti e il responsabile vZEV in base alla legislazione svizzera applicabile in "
            "materia di comunità di consumo proprio (EnG, EnV, atto di portata generale).\n\n"
            "Nei confronti del gestore di rete il vZEV si presenta come un unico cliente; il presente "
            "contratto regola esclusivamente i diritti e gli obblighi interni, la distribuzione dell'energia "
            "locale e la relativa fatturazione.\n\n"
            "Il presente contratto è concluso bilateralmente tra il responsabile vZEV e ogni "
            "partecipante; i contratti identici di tutti i partecipanti costituiscono insieme il "
            "regolamento interno del vZEV."
        ),
        "agreements_title": "Accordi",
        "local_tariff_label": "La sua tariffa per l'energia solare locale",
        "local_tariff_unit": "Centesimi / kWh",
        "local_tariff_note": "Ulteriori regole tariffarie",
        "local_tariff_note_placeholder": "",
        "tariff_pct_of": "= {pct} % della tariffa standard del gestore di rete",
        "tariff_valid_open": "dal {date}",
        "tariff_valid_label": "Validità",
        "reference_product_label": "Prodotto di riferimento",
        "billing_interval_label": "Intervallo di fatturazione",
        "payment_terms_label": "Condizioni di pagamento",
        "payment_terms_unit_sg": "giorno dalla data della fattura",
        "payment_terms_unit_pl": "giorni dalla data della fattura",
        "vat_label": "IVA",
        "vat_not_required": "Non soggetto",
        "vat_required": "Soggetto IVA",
        "additional_label": "Accordi supplementari",
        "additional_placeholder": "",
        "signatures_title": "Firme",
        "sig_intro": (
            "Con la loro firma le parti contraenti confermano di aver letto e compreso il contenuto del presente "
            "contratto e di accettarlo."
        ),
        "sig_participant": "Partecipante vZEV",
        "sig_owner": "Responsabile vZEV",
        "sig_place_date": "Luogo, Data",

        "sig_signature": "Firma",
        "page_label": "Pagina",
        "page_of": "di",
        "billing_intervals": {
            "monthly": "Mensile",
            "quarterly": "Trimestrale",
            "semi_annual": "Semestrale",
            "annual": "Annuale",
        },
        "tariff_ht": "HT (tariffa piena)",
        "tariff_nt": "NT (tariffa ridotta)",
        "tariff_flat": "Tariffa unica",
        "tariff_pct_prefix": "% della tariffa di rete",
        "tariff_rp_unit": "ct/kWh",
        "tariff_none": "—",
        "tariff_col_name": "Tariffa",
        "tariff_col_price": "Prezzo (ct/kWh)",
        "tariff_col_calc": "Calcolo",

        "contract_date_label": "Data di emissione",
        "participation_start_label": "Inizio della partecipazione",
        "appendix_title": "Allegato A – Informazioni generali (non vincolanti; il contratto prevale)",
        "meter_hint": "Il numero del punto di misura si trova sulla fattura dell'elettricità. È composto da 33 caratteri e inizia con CH.",

        "info_subtitle": "Informazioni generali per i raggruppamenti per il consumo proprio",
        "precedence_note": (
            "Il presente allegato contiene informazioni generali non vincolanti e non sostituisce una consulenza "
            "legale. In caso di divergenze prevalgono le disposizioni contrattuali numerate sulle informazioni "
            "del presente allegato. L'allegato B è vincolante per il trattamento dei dati personali."
        ),
        "info_zev_title": "Che cos'è un RCP?",
        "info_zev_text": (
            "Un raggruppamento per il consumo proprio (RCP) consente ai proprietari fondiari di utilizzare "
            "congiuntamente l'elettricità prodotta localmente (ad es. da impianti solari). I partecipanti si trovano "
            "allo stesso punto di allacciamento alla rete. Il RCP si presenta nei confronti del gestore di rete come "
            "un unico cliente e organizza la fatturazione interna in modo autonomo."
        ),
        "info_vzev_title": "Che cos'è un RCP virtuale (vRCP)?",
        "info_vzev_text": (
            "Un RCP virtuale (vRCP) estende il modello RCP: i partecipanti non devono più trovarsi allo stesso "
            "punto di allacciamento. La partecipazione è tuttavia ammessa solo se sono soddisfatti i requisiti "
            "legali per il raggruppamento per il consumo proprio nel luogo di produzione. In particolare, l'uso "
            "delle linee di allacciamento e dell'infrastruttura elettrica locale presso il punto di allacciamento "
            "interessato deve essere consentito dal diritto applicabile. Sono determinanti la valutazione tecnica "
            "e la procedura di annuncio e mutazione del gestore di rete. Ogni partecipante mantiene il proprio "
            "allacciamento. L'attribuzione del consumo proprio avviene virtualmente sulla base dei dati dei "
            "contatori intelligenti."
        ),
        "info_legal_title": "Basi legali",
        "info_legal_items": [
            "Legge sull'energia (LEne, RS 730.0), art. 16–18 — Regolamentazione del consumo proprio e del RCP",
            "Ordinanza sull'energia (OEne, RS 730.01), art. 14–18 — Disposizioni d'esecuzione",
            "Legge sull'approvvigionamento elettrico (LAEl, RS 734.7) — Accesso alla rete e approvvigionamento di base",
            "Legge federale su un approvvigionamento elettrico sicuro con le energie rinnovabili "
            "(atto modificatore unico) — Estensione al vRCP (art. 17a–17c LEne)",
        ],
        "info_rights_title": "Diritti e obblighi dei partecipanti",
        "info_rights_items": [
            "La tariffa locale dell'elettricità non deve superare la tariffa di rete ordinaria del gestore di rete.",
            "L'uscita e la disdetta sono disciplinate dalla cifra 10 del presente contratto e dal diritto cogente, "
            "in particolare dal diritto locatizio ove applicabile.",
            "Il responsabile del vRCP emette le fatture elettriche interne e amministra il raggruppamento.",
            "Le modifiche (trasloco, cambio di proprietà) devono essere comunicate senza indugio al responsabile.",
            "L'approvvigionamento di base da parte del gestore di rete resta garantito in ogni momento per tutti i partecipanti.",
        ],
        "info_liability_title": "Responsabilità solidale",
        "info_liability_text": (
            "Tutti i partecipanti di un RCP o vRCP sono solidalmente responsabili nei confronti del gestore di "
            "rete per i costi di rete e l'elettricità acquistata (art. 17 cpv. 2 LEne). Ciò significa che se "
            "un partecipante non è in grado di pagare la propria fattura dell'elettricità, gli altri partecipanti "
            "possono essere chiamati a coprire l'importo dovuto. La ripartizione interna dei costi è gestita dal "
            "responsabile del vRCP attraverso la fatturazione dell'elettricità."
        ),
        "info_tariff_title": "Disposizioni tariffarie",
        "info_tariff_text": (
            "La tariffa per l'elettricità prodotta localmente segue la regola tariffaria della cifra 5 "
            "(percentuale del prodotto standard esterno del gestore di rete o tariffa fissa). Per legge non "
            "deve superare la tariffa ordinaria del gestore di rete (inclusi utilizzo della rete, tasse e "
            "supplementi). La quota di elettricità che non può essere coperta localmente continua a essere "
            "acquistata alla tariffa ordinaria dal gestore di rete."
        ),
        "duration_title": "Durata del contratto e disdetta",
        "duration_text": (
            "Il presente contratto è stipulato a tempo indeterminato ed entra in vigore con la firma di entrambe "
            "le parti. Il proprietario può, nella misura consentita dal diritto applicabile, disdire il presente "
            "contratto per iscritto con un preavviso di due "
            "mesi per la fine di un periodo di fatturazione, fatto salvo il processo di mutazione richiesto dal "
            "gestore di rete. Per locatari e affittuari, la partecipazione, l'uscita e la prosecuzione della "
            "fornitura sono disciplinate dal diritto locatizio svizzero cogente, dal contratto di locazione e "
            "dalle disposizioni applicabili del diritto dell'energia. Se un locatario ha diritto all'uscita, si "
            "applicano il termine e la procedura previsti dalla legge. L'uscita diventa effettiva solo quando "
            "è attuata nella soluzione di misurazione e fornitura richiesta dal gestore di rete."
        ),
        "jurisdiction_title": "Comunicazione, controversie e disposizioni finali",
        "jurisdiction_text": (
            "Il presente contratto è soggetto al diritto svizzero. Il foro competente è la sede del vZEV "
            "o il domicilio del responsabile vZEV. Le modifiche richiedono la forma scritta. Qualora una "
            "disposizione fosse nulla, il contratto resta valido per il resto; le parti sostituiscono la "
            "disposizione nulla con una valida che si avvicini il più possibile allo scopo.\n\n"
            "Se i presupposti legali o le esigenze del gestore di rete mutano in modo tale che il vZEV "
            "non può più essere gestito, il responsabile vZEV può scioglierlo con termine adeguato; le "
            "parti sono allora rifornite esclusivamente alla tariffa esterna standard."
        ),
        "definitions_title": "Definizioni",
        "definitions_items": [
            "« vZEV »: raggruppamento virtuale per il consumo proprio ai sensi degli art. 16–18 EnG, "
            "14–18 EnV e 17a–17c EnG.",
            "« Responsabile vZEV »: la parte che registra il vZEV presso il gestore di rete, lo amministra e "
            "organizza la fatturazione interna.",
            "« Partecipante »: ogni parte che partecipa al vZEV e consuma energia locale (proprietario o "
            "inquilino).",
            "« Gestore di rete »: l'azienda elettrica alla cui rete è allacciato il vZEV.",
            "« Impianto di produzione »: l'impianto (in particolare fotovoltaico) la cui produzione locale è "
            "attribuita ai partecipanti.",
            "« Punto di misurazione »: contatore intelligente con numero di 33 caratteri che inizia con "
            "« CH », che rileva consumo o produzione.",
            "« Tariffa esterna standard »: la tariffa ordinaria del gestore di rete per energia, utilizzo "
            "della rete e tasse, senza vZEV.",
        ],
        "manager_title": "Organizzazione e compiti del responsabile vZEV",
        "manager_text": (
            "Il responsabile vZEV rappresenta il vZEV nei confronti del gestore di rete e delle autorità, "
            "provvede alla registrazione e a tutte le mutazioni correnti e garantisce i presupposti tecnici e "
            "giuridici (in particolare contatori intelligenti e potenza di produzione richiesta). Svolge i "
            "compiti operativi con propria competenza; l'ammissione di nuovi partecipanti e le modifiche "
            "del presente contratto richiedono il consenso di tutti i partecipanti. Il responsabile "
            "vZEV informa i partecipanti almeno una volta all'anno su tariffe, produzione e "
            "attribuzione."
        ),
        "manager_duties": [
            "emissione e invio puntuale delle fatture interne dell'elettricità;",
            "tenuta del registro dei partecipanti e gestione delle tariffe;",
            "organizzazione dell'accesso ai dati dei contatori intelligenti;",
            "trasmissione della fattura del gestore di rete e ripartizione interna dei costi;",
            "informazione dei partecipanti sulle modifiche normative che riguardano il vZEV.",
        ],
        "clause_tariff_rule_lead": "Regola tariffaria.",
        "clause_tariff_cap_lead": "Limite tariffario.",
        "clause_tariff_adjustment_lead": "Comunicazione e disdetta.",
        "clause_billing_lead": "Fatturazione e mora.",

        "clause_tariff_rule_pct": (
            "Il prezzo dell'energia prodotta localmente e consumata "
            "all'interno del vZEV corrisponde al {pct} % del prodotto standard esterno applicabile del "
            "gestore di rete (energia, utilizzo della rete, tasse e supplementi; esclusi i costi una tantum "
            "e l'IVA, salvo diverso accordo espresso). La tariffa indicata si applica esclusivamente all'energia "
            "prodotta localmente e attribuita al partecipante; elettricità di rete, utilizzo della rete, tasse, "
            "costi di misurazione e costi amministrativi convenuti sono fatturati separatamente secondo le regole "
            "di attribuzione. La tariffa si adegua automaticamente quando il "
            "gestore di rete modifica i propri prezzi; il responsabile vZEV comunica ai partecipanti il "
            "valore tariffario in vigore con ogni fattura o almeno una volta all'anno."
        ),
        "clause_tariff_rule_flat": (
            "La tariffa per l'energia prodotta localmente e consumata "
            "all'interno del vZEV è una tariffa fissa, come indicato nella tabella tariffaria della "
            "presente cifra. La tariffa indicata si applica esclusivamente all'energia prodotta localmente e attribuita al partecipante; elettricità di rete, utilizzo della rete, tasse, costi di misurazione e costi amministrativi convenuti sono fatturati separatamente secondo le regole di attribuzione. Viene verificata annualmente e adeguata in caso di modifiche dei prezzi del "
            "gestore di rete; le nuove tariffe sono comunicate ai partecipanti almeno un mese prima."
        ),
        "clause_tariff_cap": (
            "La tariffa per l'energia locale non deve superare la tariffa esterna standard del gestore "
            "di rete per la stessa quantità di energia. Per gli inquilini devono essere rispettate le regole "
            "applicabili del diritto locatizio e del diritto dell'energia in materia di prezzi e costi. Se si "
            "applica il metodo semplificato previsto dalla legge con l'80 %, tale percentuale si riferisce alla "
            "base dei costi definita dalla legge; negli altri casi devono essere documentati il calcolo effettivo "
            "dei costi e il limite applicabile. La tariffa indicata si applica esclusivamente all'energia prodotta "
            "localmente e attribuita al partecipante; elettricità di rete, utilizzo della rete, tasse, costi di "
            "misurazione e costi amministrativi convenuti sono fatturati separatamente secondo le regole di "
            "attribuzione. La regola tariffaria della presente cifra precisa se l'IVA è inclusa; prevale il diritto "
            "cogente."
        ),
        "clause_tariff_adjustment": (
            "Le modifiche tariffarie sono comunicate ai partecipanti almeno un mese prima della "
            "loro entrata in vigore. I diritti di disdetta o uscita conseguenti a una modifica tariffaria sono "
            "disciplinati dalla cifra 10, dal diritto cogente e, se necessario, dalla procedura richiesta dal "
            "gestore di rete."
        ),
        "clause_billing": (
            "Il responsabile vZEV paga la fattura del gestore di rete e ripartisce i costi internamente "
            "secondo le regole di attribuzione convenute. Le fatture sono pagabili entro il termine convenuto; "
            "dopo sollecito maturano un interesse moratorio del 5 % annuo e ragionevoli spese di sollecito. In "
            "caso di fatture ripetutamente non pagate, il responsabile vZEV può, dopo sollecito e fatto salvo il "
            "diritto cogente, disdire la partecipazione conformemente alla cifra 10. Ogni conseguente modifica "
            "della soluzione di misurazione o fornitura è disciplinata dal diritto applicabile e dalle esigenze "
            "del gestore di rete."
        ),
        "metering_title": "Misurazione e attribuzione",
        "metering_text": (
            "Tutte le parti utilizzano contatori intelligenti conformi alle prescrizioni del gestore di rete. "
            "L'attribuzione avviene per intervallo di misurazione: l'energia locale è la parte della produzione "
            "consumata nell'intervallo, ripartita in proporzione ai consumi simultanei; la produzione non "
            "utilizzata immessa in rete è attribuita proporzionalmente agli impianti di produzione e la "
            "remunerazione dell'immissione spetta ai proprietari dell'impianto. Base della fatturazione interna "
            "sono i valori kWh misurati per periodo; i dati mancanti o implausibili sono provvisoriamente stimati "
            "dal responsabile vZEV sulla base dei periodi precedenti. Non appena sono disponibili dati di misura "
            "validati, questi sostituiscono la stima; le differenze sono accreditate o addebitate sulla fattura "
            "successiva."
        ),
        "liability_title": "Responsabilità e regresso",
        "liability_text": (
            "Nei confronti del gestore di rete tutti i partecipanti rispondono in solido dei costi di rete e "
            "di approvvigionamento (art. 17 EnG); nei rapporti interni ciascuna parte sopporta la propria "
            "quota. Se una parte non copre la propria quota, deve un indennizzo alle altre parti e al "
            "responsabile vZEV. Non esiste alcun diritto a una quantità minima di energia locale; in caso di "
            "guasto o produzione ridotta, la differenza è coperta alla tariffa esterna standard. Nessuna "
            "responsabilità per eventi al di fuori del controllo del responsabile vZEV (disturbi di rete, "
            "provvedimenti ufficiali, guasti di sistema). L'approvvigionamento di base da parte del "
            "gestore di rete resta garantito in ogni momento."
        ),
        "membership_title": "Adesione, uscita e mutazioni",
        "membership_text": (
            "Nuove parti possono aderire solo se sono soddisfatti i requisiti legali per il raggruppamento per "
            "il consumo proprio nel luogo di produzione. In particolare, l'uso delle linee di allacciamento e "
            "dell'infrastruttura elettrica locale presso il punto di allacciamento interessato deve essere "
            "consentito; sono determinanti la valutazione tecnica e la procedura di annuncio e mutazione del "
            "gestore di rete. Ciascuna parte mantiene il proprio allacciamento alla rete. L'adesione richiede "
            "la firma scritta del presente contratto. Le mutazioni (trasloco, vendita della casa, ecc.) vanno "
            "comunicate al responsabile vZEV al più tardi 14 giorni dopo esserne venuti a conoscenza. In caso "
            "di passaggio di proprietà, il nuovo proprietario entra nel contratto con consenso scritto; in "
            "mancanza è rifornito esclusivamente alla tariffa esterna standard. In caso di uscita di una parte, "
            "la sua quota di produzione e costi è ripartita proporzionalmente tra i partecipanti rimanenti."
        ),
        "privacy_title": "Protezione dei dati",
        "privacy_text": (
            "Il responsabile vZEV è il titolare del trattamento ai sensi della legge sulla protezione dei "
            "dati (LPD, RS 235.1). Tratta i dati di contatto e i numeri dei punti di misurazione nonché i "
            "profili di consumo e produzione esclusivamente per l'attribuzione, la fatturazione e "
            "l'amministrazione del vZEV. I dati sono trasmessi al gestore di rete e ai fornitori di "
            "fatturazione solo nella misura necessaria. I dati sono conservati per la durata della "
            "partecipazione e, oltre questa, soltanto per quanto richiesto dagli obblighi legali di "
            "conservazione; i dati non più necessari vengono cancellati. Le parti "
            "hanno diritto di accesso, rettifica e, ove legalmente possibile, cancellazione dei propri "
            "dati."
        ),
        "privacy_short": (
            "Il responsabile vZEV tratta i dati di contatto e di misurazione esclusivamente per "
            "l'attribuzione, la fatturazione e l'amministrazione del vZEV; i dati sono trasmessi al "
            "gestore di rete e ai prestatori di fatturazione solo nella misura necessaria. L'informativa "
            "completa sulla protezione dei dati figura nell'allegato B."
        ),
        "privacy_controller_title": "Titolare del trattamento",
        "privacy_controller_text": (
            "Il titolare del trattamento ai sensi della legge sulla protezione dei dati (LPD, "
            "RS 235.1) è il responsabile vZEV indicato alla cifra 1:"
        ),
        "privacy_purposes_title": "Dati trattati e finalità",
        "privacy_purposes_items": [
            "Dati di contatto e di identificazione (nome, indirizzo, e-mail, telefono) per l'esecuzione del contratto e la comunicazione;",
            "Numeri dei punti di misurazione e dati dei contatori per l'attribuzione di consumo e produzione;",
            "Profili di consumo e di produzione per la fatturazione e l'amministrazione del vZEV.",
        ],
        "privacy_recipients_title": "Destinatari",
        "privacy_recipients_text": (
            "I dati sono trasmessi al gestore di rete e ai fornitori di servizi di fatturazione "
            "solo nella misura necessaria al funzionamento del vZEV. Nessuna trasmissione per "
            "altri scopi viene effettuata; una trasmissione all'estero avviene soltanto se "
            "legalmente ammissibile e necessaria."
        ),
        "privacy_retention_title": "Durata di conservazione",
        "privacy_retention_col_data": "Categoria di dati",
        "privacy_retention_col_period": "Durata di conservazione",
        "privacy_retention_categories": [
            "Documenti di fatturazione e contratti",
            "Dati di misurazione aggregati",
            "Dati di misurazione ad alta risoluzione",
            "Dati di contatto e contrattuali",
        ],
        "privacy_retention_periods": [
            "10 anni (obbligo legale di conservazione)",
            "10 anni (base di fatturazione)",
            "Cancellati appena non più necessari alla fatturazione; restano salvi i termini legali",
            "Durata della partecipazione, poi secondo i termini legali",
        ],
        "privacy_rights_title": "Diritti dei partecipanti",
        "privacy_rights_items": [
            "Accesso ai propri dati trattati;",
            "Rettifica di dati inesatti;",
            "Cancellazione ove legalmente possibile e se nessun obbligo di conservazione si oppone;",
            "Limitazione del trattamento e portabilità dei dati secondo la LPD;",
            "Ricorso all'Incaricato federale della protezione dei dati e della trasparenza (IFPDT).",
        ],
        "appendix_b_title": "Allegato B",
        "appendix_b_subtitle": "Informativa sulla protezione dei dati – parte integrante del contratto",
        "communication_text": (
            "Le comunicazioni via e-mail all'ultimo indirizzo conosciuto si considerano ricevute tre giorni "
            "dopo l'invio. In caso di controversia le parti cercano prima una soluzione amichevole; in "
            "mancanza decide il tribunale competente."
        ),
        "info_privacy_title": "Protezione dei dati",
        "info_privacy_text": (
            "Il trattamento dei dati personali e di misurazione da parte del responsabile vZEV è retto "
            "dall'informativa vincolante sulla protezione dei dati di cui all'allegato B del presente "
            "contratto."
        ),
    },
    "en": {
        "contract_title": "vZEV Participation Agreement",
        "parties_title": "Contracting Parties",
        "participant_label": 'Participant in the vZEV (hereinafter "vZEV Participant")',
        "owner_label": 'Responsible party for the vZEV (hereinafter "vZEV Manager")',

        "field_address": "Address, City",
        "field_phone": "Phone",
        "field_email": "E-mail",
        "field_meter": "Metering point number",

        "meter_none": "No metering point assigned yet",

        "field_meter_pv": "Metering point number (PV / feed-in)",
        "subject_title": "Purpose and scope",
        "subject_text": (
            "This agreement governs participation in the vZEV and the internal relationship between the "
            "participants and the vZEV Manager under the applicable Swiss energy legislation on "
            "self-consumption communities (EnG, EnV, omnibus act).\n\n"
            "Towards the grid operator, the vZEV acts as a single customer; this agreement exclusively "
            "governs the internal rights and obligations, the internal distribution of electricity and the "
            "billing of local energy.\n\n"
            "This agreement is concluded bilaterally between the vZEV Manager and each participant; the "
            "identical agreements of all participants together form the internal framework of the "
            "vZEV."
        ),
        "agreements_title": "Agreements",
        "local_tariff_label": "Your local solar-energy tariff",
        "local_tariff_unit": "CHF cents / kWh",
        "local_tariff_note": "Further tariff rules",
        "local_tariff_note_placeholder": "",
        "tariff_pct_of": "= {pct} % of the grid operator's standard tariff",
        "tariff_valid_open": "from {date}",
        "tariff_valid_label": "Validity",
        "reference_product_label": "Reference product",
        "billing_interval_label": "Billing interval",
        "payment_terms_label": "Payment terms",
        "payment_terms_unit_sg": "day from invoice date",
        "payment_terms_unit_pl": "days from invoice date",
        "vat_label": "VAT",
        "vat_not_required": "Not liable",
        "vat_required": "VAT liable",
        "additional_label": "Additional agreements",
        "additional_placeholder": "",
        "signatures_title": "Signatures",
        "sig_intro": (
            "By signing, the contracting parties confirm that they have read and understood the content of "
            "this agreement and accept it."
        ),
        "sig_participant": "vZEV Participant",
        "sig_owner": "vZEV Manager",
        "sig_place_date": "Place, Date",

        "sig_signature": "Signature",
        "page_label": "Page",
        "page_of": "of",
        "billing_intervals": {
            "monthly": "Monthly",
            "quarterly": "Quarterly",
            "semi_annual": "Semi-annual",
            "annual": "Annual",
        },
        "tariff_ht": "HT (peak)",
        "tariff_nt": "NT (off-peak)",
        "tariff_flat": "Flat rate",
        "tariff_pct_prefix": "% of grid tariff",
        "tariff_rp_unit": "Rp./kWh",
        "tariff_none": "—",
        "tariff_col_name": "Tariff",
        "tariff_col_price": "Price (Rp./kWh)",
        "tariff_col_calc": "Calculation",

        "contract_date_label": "Issue date",
        "participation_start_label": "Participation start",
        "appendix_title": "Appendix A – General information (non-binding; the agreement prevails)",
        "meter_hint": "The metering point number can be found on your electricity bill. It consists of 33 characters starting with CH.",

        "info_subtitle": "General information on self-consumption communities in Switzerland",
        "precedence_note": (
            "This appendix contains general, non-binding information and does not constitute legal advice. In "
            "case of conflict, the numbered clauses of the agreement prevail over the information in this "
            "appendix. Appendix B is binding for the processing of personal data."
        ),
        "info_zev_title": "What is a ZEV?",
        "info_zev_text": (
            "A self-consumption community (ZEV — Zusammenschluss zum Eigenverbrauch) allows property owners to "
            "collectively use locally produced electricity (e.g. from solar installations). Participants are "
            "connected at the same grid connection point. The ZEV acts as a single customer toward the grid operator "
            "and manages internal electricity billing independently."
        ),
        "info_vzev_title": "What is a virtual ZEV (vZEV)?",
        "info_vzev_text": (
            "A virtual ZEV (vZEV) extends the ZEV model: participants no longer need to share the same grid "
            "connection point. Participation is permitted only where the statutory requirements for common "
            "self-consumption at the place of production are met. In particular, the use of service lines and "
            "local electrical infrastructure at the relevant grid connection point must be permitted under "
            "applicable law. The grid operator's technical assessment and registration/mutation process is "
            "decisive. Each participant retains their own grid connection. Self-consumption allocation is "
            "performed virtually based on smart meter data."
        ),
        "info_legal_title": "Legal basis",
        "info_legal_items": [
            "Energy Act (EnG, SR 730.0), Art. 16–18 — Self-consumption and ZEV regulations",
            "Energy Ordinance (EnV, SR 730.01), Art. 14–18 — Implementing provisions",
            "Electricity Supply Act (StromVG, SR 734.7) — Grid access and universal service obligation",
            "Federal Act on a Secure Electricity Supply with Renewable Energies (Mantelerlass) — "
            "Extension to vZEV (Art. 17a–17c EnG)",
        ],
        "info_rights_title": "Participant rights and obligations",
        "info_rights_items": [
            "The local electricity tariff must not exceed the regular grid tariff of the grid operator.",
            "Termination and withdrawal are governed by section 10 of this agreement and by mandatory law, in "
            "particular tenancy law where applicable.",
            "The vZEV manager issues internal electricity invoices and administers the community.",
            "Changes (relocation, change of ownership) must be reported to the vZEV manager without delay.",
            "Universal grid supply by the grid operator remains guaranteed at all times for all participants.",
        ],
        "info_liability_title": "Joint and several liability",
        "info_liability_text": (
            "All participants of a ZEV or vZEV are jointly and severally liable toward the grid operator for "
            "grid costs and purchased electricity (Art. 17 para. 2 EnG). This means that if one participant "
            "cannot pay their electricity bill, the other participants may be held responsible for the "
            "outstanding amount. The internal allocation of costs is managed by the vZEV manager through "
            "the electricity billing."
        ),
        "info_tariff_title": "Tariff provisions",
        "info_tariff_text": (
            "The tariff for locally produced electricity follows the tariff rule in section 5 (a percentage "
            "of the grid operator's external standard product or a fixed tariff). By law, it must not exceed "
            "the regular electricity tariff of the grid operator (including grid usage, levies, and "
            "surcharges). Any electricity that cannot be covered locally continues to be purchased at the "
            "regular tariff from the grid operator."
        ),
        "duration_title": "Contract duration and termination",
        "duration_text": (
            "This agreement is concluded for an indefinite period and takes effect upon signature by both parties. "
            "An owner may, where permitted by applicable law, terminate this agreement in writing with two months' "
            "notice at the end of a billing "
            "period, subject to the grid operator's required mutation process. For tenants and leaseholders, "
            "participation, withdrawal and continued supply are governed by mandatory Swiss tenancy law, the "
            "lease agreement and applicable energy-law requirements. Where a tenant is entitled to withdraw, "
            "the notice period and procedure required by law apply. Any exit takes effect only once it has been "
            "implemented in the metering and supply arrangement required by the grid operator."
        ),
        "jurisdiction_title": "Communication, disputes and final provisions",
        "jurisdiction_text": (
            "This agreement is governed by Swiss law. The place of jurisdiction is the registered seat "
            "of the vZEV or the domicile of the vZEV Manager. Amendments require written form. Should any "
            "provision be invalid, the remainder of the agreement stays in force; the parties replace the "
            "invalid provision with a valid one that comes closest to its purpose.\n\n"
            "If legal requirements or the grid operator's requirements change such that the vZEV can no "
            "longer be continued, the vZEV Manager may dissolve it with appropriate notice; the parties "
            "are then supplied exclusively at the external standard tariff."
        ),
        "definitions_title": "Definitions",
        "definitions_items": [
            "\"vZEV\": virtual self-consumption community pursuant to Art. 16–18 EnG, Art. 14–18 EnV "
            "and Art. 17a–17c EnG.",
            "\"vZEV Manager\": the party that registers the vZEV with the grid operator, administers it and "
            "organises the internal billing.",
            "\"Participant\": any party participating in the vZEV and drawing local energy (owner or "
            "tenant).",
            "\"Grid operator\": the electricity supply company to whose grid the vZEV is connected.",
            "\"Production plant\": the generation plant (in particular photovoltaic) whose local production "
            "is allocated to the participants.",
            "\"Metering point\": the smart meter with a 33-character number beginning with \"CH\" that "
            "records consumption or production.",
            "\"External standard tariff\": the grid operator's regular tariff for energy, grid usage and "
            "levies without the vZEV.",
        ],
        "manager_title": "Organisation and duties of the vZEV Manager",
        "manager_text": (
            "The vZEV Manager represents the vZEV towards the grid operator and the authorities, handles the "
            "registration and all ongoing mutations and ensures the technical and legal prerequisites (in "
            "particular smart meters and the required production capacity). Operational tasks are carried out "
            "at the Manager's own discretion; the admission of new participants and any amendment of this "
            "agreement require the consent of all participants. The vZEV Manager informs the "
            "participants at least once a year about tariffs, production and allocation."
        ),
        "manager_duties": [
            "timely issuance and delivery of the internal electricity invoices;",
            "keeping the participant register and maintaining the tariffs;",
            "organising access to the smart meter data;",
            "passing on the grid operator's invoice and internal cost allocation;",
            "informing participants of regulatory changes affecting the vZEV.",
        ],
        "clause_tariff_rule_lead": "Tariff rule.",
        "clause_tariff_cap_lead": "Tariff cap.",
        "clause_tariff_adjustment_lead": "Notification and termination.",
        "clause_billing_lead": "Billing and default.",

        "clause_tariff_cap": (
            "The local energy tariff must not exceed the grid operator's external standard tariff for the "
            "same amount of energy. For tenants, applicable tenancy-law and energy-law pricing and cost rules "
            "must be observed. Where the statutory simplified method using 80% is applied, that percentage "
            "applies to the legally defined cost base; otherwise, the effective cost calculation and applicable "
            "cap must be documented. The stated tariff applies solely to locally produced electricity allocated "
            "to the participant; grid electricity, grid-use charges, levies, metering costs and agreed "
            "administration costs are charged separately in accordance with the allocation rules. The tariff rule "
            "in this section states whether VAT is included; mandatory law prevails."
        ),
        "clause_tariff_rule_pct": (
            "The price for locally produced electricity consumed within the "
            "vZEV amounts to {pct} % of the grid operator's applicable external standard product for the "
            "participant (energy, grid usage, levies and surcharges; excluding one-off charges and VAT "
            "unless expressly agreed otherwise). The stated tariff applies solely to locally produced electricity "
            "allocated to the participant; grid electricity, grid-use charges, levies, metering costs and agreed "
            "administration costs are charged separately in accordance with the allocation rules. The tariff "
            "adjusts automatically when the grid operator "
            "changes its prices; the vZEV Manager informs participants of the currently applicable tariff "
            "value with each invoice or at least annually."
        ),
        "clause_tariff_rule_flat": (
            "The tariff for locally produced electricity consumed within the "
            "vZEV is a fixed tariff as set out in the tariff table in this section. The stated tariff applies solely to "
            "locally produced electricity allocated to the participant; grid electricity, grid-use charges, "
            "levies, metering costs and agreed administration costs are charged separately in accordance with the "
            "allocation rules. It is reviewed annually "
            "and adjusted when the grid operator's prices change; new tariffs are notified to participants "
            "at least one month in advance."
        ),
        "clause_tariff_adjustment": (
            "Tariff changes are notified to participants at least one month before they take "
            "effect. Any termination or withdrawal following a tariff change is governed by section 10, "
            "mandatory law and, where required, the procedure prescribed by the grid operator."
        ),
        "clause_billing": (
            "The vZEV Manager pays the grid operator's invoice and allocates the costs internally according "
            "to the agreed allocation rules. Invoices are payable within the agreed period; after a reminder, "
            "default interest of 5% p.a. and reasonable reminder fees fall due. In the case of repeatedly unpaid "
            "invoices, the vZEV Manager may, after reminders and subject to mandatory law, terminate "
            "participation in accordance with section 10. Any resulting change in supply or metering "
            "arrangements is subject to applicable law and the grid operator's requirements."
        ),
        "metering_title": "Metering and allocation",
        "metering_text": (
            "All parties use smart meters in accordance with the grid operator's requirements. Local "
            "production is allocated per metering interval: local energy is the share of production "
            "consumed within the interval, distributed in proportion to simultaneous consumption; unused "
            "production exported to the grid is allocated pro rata to the production plants, and the "
            "feed-in remuneration belongs to the owners of the production plant. "
            "Internal billing is based on the kWh values measured per billing period; missing or implausible "
            "meter data are provisionally estimated by the vZEV Manager based on previous periods. Once "
            "validated meter data become available, they replace the estimate; resulting differences are "
            "credited or charged on the next invoice."
        ),
        "liability_title": "Liability and recourse",
        "liability_text": (
            "Towards the grid operator, all participants are jointly and severally liable for grid and "
            "supply costs (Art. 17 EnG); internally, each party bears its own share. If a party does not "
            "cover its share, it owes compensation to the other parties and the vZEV Manager. There is no "
            "entitlement to a minimum amount of local energy; if the plant fails or produces less, the "
            "difference is covered at the external standard tariff. No liability exists for events outside "
            "the vZEV Manager's control (grid disturbances, official measures, system failures). "
            "Universal service supply by the grid operator remains guaranteed at all times."
        ),
        "membership_title": "Entry, exit and mutations",
        "membership_text": (
            "New parties may join only where the statutory requirements for common self-consumption at the place "
            "of production are met. In particular, the use of service lines and local electrical infrastructure "
            "at the relevant grid connection point must be permitted under applicable law; the grid operator's "
            "technical assessment and registration/mutation process is decisive. Each party retains its own grid "
            "connection. Joining requires signing this agreement in writing. Mutations (relocation, sale of the "
            "property, etc.) must be reported to the vZEV Manager within 14 days of becoming known. Upon transfer of "
            "ownership, the new owner enters the agreement with written consent; otherwise they are supplied "
            "exclusively at the external standard tariff. If a party leaves, its share of production and "
            "costs is redistributed pro rata among the remaining participants."
        ),
        "privacy_title": "Data protection",
        "privacy_text": (
            "The vZEV Manager is the data controller under the Federal Act on Data Protection (FADP, SR "
            "235.1). It processes contact data and metering point numbers as well as consumption and "
            "production profiles exclusively for allocation, billing and administration of the vZEV. Data "
            "are disclosed to the grid operator and to billing service providers only to the extent "
            "necessary. Data are retained for the duration of participation and, beyond that, only as long "
            "as statutory retention obligations require; data that are no longer needed are deleted. The "
            "parties have the right to access, rectification and, where legally possible, deletion of their "
            "data."
        ),
        "privacy_short": (
            "The vZEV Manager processes contact and metering data exclusively for allocation, billing and "
            "administration of the vZEV; data are disclosed to the grid operator and billing service "
            "providers only to the extent necessary. The full privacy notice is set out in Appendix B."
        ),
        "privacy_controller_title": "Controller",
        "privacy_controller_text": (
            "The controller within the meaning of the Swiss Federal Act on Data Protection "
            "(FADP, SR 235.1) is the vZEV Manager named in section 1:"
        ),
        "privacy_purposes_title": "Data processed and purposes",
        "privacy_purposes_items": [
            "Contact and identification data (name, address, e-mail, telephone) for contract administration and communication;",
            "Metering-point and smart-meter data for allocating consumption and production;",
            "Consumption and production profiles for billing and administration of the vZEV.",
        ],
        "privacy_recipients_title": "Recipients",
        "privacy_recipients_text": (
            "Data is disclosed only to the grid operator and to contracted billing service "
            "providers to the extent required for operating the vZEV. No transfer for other "
            "purposes is made; transfer abroad occurs only where legally permissible and "
            "necessary."
        ),
        "privacy_retention_title": "Retention periods",
        "privacy_retention_col_data": "Data category",
        "privacy_retention_col_period": "Retention period",
        "privacy_retention_categories": [
            "Billing documents and contracts",
            "Aggregated metering data",
            "High-resolution metering data",
            "Contact and contract data",
        ],
        "privacy_retention_periods": [
            "10 years (statutory retention obligation)",
            "10 years (basis for billing)",
            "Deleted as soon as no longer needed for billing; statutory periods reserved",
            "Duration of participation, then per statutory periods",
        ],
        "privacy_rights_title": "Rights of participants",
        "privacy_rights_items": [
            "Access to your processed personal data;",
            "Rectification of inaccurate data;",
            "Erasure where legally possible and no retention obligation applies;",
            "Restriction of processing and data portability under the FADP;",
            "Complaint to the Federal Data Protection and Information Commissioner (FDPIC).",
        ],
        "appendix_b_title": "Appendix B",
        "appendix_b_subtitle": "Privacy notice – integral part of the agreement",
        "communication_text": (
            "Notices by email to the last known address are deemed received three days after sending. In the "
            "event of a dispute, the parties first seek an amicable solution; failing that, the competent "
            "court decides."
        ),
        "info_privacy_title": "Data protection",
        "info_privacy_text": (
            "How the vZEV Manager processes personal and metering data is governed by the binding privacy "
            "notice in Appendix B of this agreement."
        ),
    },
}
