"""
Contract PDF generation for ZEV participation agreements.
Renders an HTML template via Django's template engine and converts it to PDF
using WeasyPrint.
"""
import logging
from datetime import date
from decimal import Decimal

from django.template.loader import render_to_string
from weasyprint import HTML

from tariffs.models import BillingMode, EnergyType, PeriodType
from zev.models import MeteringPointType

logger = logging.getLogger(__name__)

CONTRACT_TEMPLATE_NAME = "contracts/participant_contract_pdf.html"

CONTRACT_TRANSLATIONS: dict[str, dict] = {
    "de": {
        "contract_title": "Teilnahmevertrag vZEV",
        "parties_title": "Vertragsparteien",
        "participant_label": 'Teilnehmer am vZEV (nachfolgend «vZEV-Teilnehmer» genannt)',
        "owner_label": 'Verantwortung über vZEV (nachfolgend «vZEV-Verantwortlicher» genannt)',
        "field_name": "Vorname, Name",
        "field_address": "Adresse, Ort",
        "field_phone": "Telefon",
        "field_email": "E-Mail",
        "field_building": "Gebäude / Wohnung",
        "field_meter": "Messpunktnummer",
        "field_meter_second": "Zweite Messpunktnummer (nur falls vorhanden)",
        "field_meter_pv": "Messpunktnummer (PV / Rückspeisung)",
        "subject_title": "Vertragsgegenstand",
        "subject_text": (
            "Der vZEV-Teilnehmer erklärt sich mit der Teilnahme am virtuellen Zusammenschluss zum Eigenverbrauch "
            "(nachfolgend «vZEV» genannt) einverstanden. Der vZEV-Verantwortliche wird zur Anmeldung und Verwaltung "
            "des vZEV beim Netzbetreiber bevollmächtigt.\n\n"
            "Der vZEV-Verantwortliche ist für die Verwaltung (Mutationen, Pflege der Tarife etc.) und die pünktliche "
            "Erstellung der Stromrechnungen verantwortlich.\n\n"
            "Mutationen (Wegzug, Hausverkauf o. Ä.) sind dem vZEV-Verantwortlichen rasch möglichst, spätestens jedoch "
            "nach 14 Tagen zu melden.\n\n"
            "Der vZEV-Teilnehmer akzeptiert, künftig die erstellten Stromrechnungen zu erhalten und in vereinbarter "
            "Frist zu begleichen."
        ),
        "agreements_title": "Vereinbarungen",
        "local_tariff_label": "Tarif für lokale ZEV-Energie",
        "local_tariff_unit": "Rappen / kWh",
        "local_tariff_note": "Tarif für Folgejahre / Regelung",
        "local_tariff_note_placeholder": (
            "Beispiel: Der Tarif für lokale ZEV-Energie wird auf 65 % des totalen Netzstrompreises festgelegt "
            "(Energie inkl. Netzkosten, Abgaben etc.). Mindestens jedoch soviel wie die reinen Energiekosten "
            "des Netzbetreibers im jeweiligen Jahr."
        ),
        "billing_interval_label": "Abrechnungsintervall",
        "payment_terms_label": "Zahlungskonditionen",
        "payment_terms_unit": "Tage ab Rechnungsdatum",
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
        "sig_name": "Name, Vorname",
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
        "tariff_rp_unit": "Rp/kWh",
        "tariff_none": "—",
        "tariff_col_name": "Tarif",
        "tariff_col_price": "Preis (Rp/kWh)",
        "tariff_col_calc": "Berechnung",
        "contract_date": "Datum Vertragsabschluss",
        "meter_hint": "Die Messpunktnummer ist auf der Stromrechnung zu finden. Sie besteht aus 33 Stellen und beginnt mit CH.",
    },
    "fr": {
        "contract_title": "Contrat de participation vZEV",
        "parties_title": "Parties contractantes",
        "participant_label": "Participant au vZEV (ci-après «participant vZEV»)",
        "owner_label": "Responsable du vZEV (ci-après «responsable vZEV»)",
        "field_name": "Prénom, Nom",
        "field_address": "Adresse, Lieu",
        "field_phone": "Téléphone",
        "field_email": "E-mail",
        "field_building": "Bâtiment / Appartement",
        "field_meter": "Numéro de point de mesure",
        "field_meter_second": "Deuxième numéro de point de mesure (si disponible)",
        "field_meter_pv": "Numéro de point de mesure (PV / injection)",
        "subject_title": "Objet du contrat",
        "subject_text": (
            "Le participant vZEV consent à la participation au regroupement virtuel pour la consommation propre "
            "(ci-après «vZEV»). Le responsable vZEV est autorisé à enregistrer et gérer le vZEV auprès du "
            "gestionnaire de réseau.\n\n"
            "Le responsable vZEV est chargé de la gestion (mutations, maintenance des tarifs, etc.) et de "
            "l'établissement ponctuel des factures d'électricité.\n\n"
            "Les mutations (déménagement, vente de bien, etc.) doivent être signalées au responsable vZEV le plus "
            "rapidement possible, au plus tard dans les 14 jours.\n\n"
            "Le participant vZEV accepte de recevoir les factures d'électricité et de les régler dans le délai convenu."
        ),
        "agreements_title": "Conventions",
        "local_tariff_label": "Tarif pour l'énergie locale ZEV",
        "local_tariff_unit": "Centimes / kWh",
        "local_tariff_note": "Tarif pour les années suivantes / règle",
        "local_tariff_note_placeholder": "",
        "billing_interval_label": "Intervalle de facturation",
        "payment_terms_label": "Conditions de paiement",
        "payment_terms_unit": "jours à compter de la date de facturation",
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
        "sig_name": "Nom, Prénom",
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
        "contract_date": "Date de conclusion du contrat",
        "meter_hint": "Le numéro de point de mesure figure sur la facture d'électricité. Il comporte 33 caractères et commence par CH.",
    },
    "it": {
        "contract_title": "Contratto di partecipazione ZEV virtuale",
        "parties_title": "Parti contraenti",
        "participant_label": "Partecipante al vZEV (di seguito «partecipante vZEV»)",
        "owner_label": "Responsabile del vZEV (di seguito «responsabile vZEV»)",
        "field_name": "Nome, Cognome",
        "field_address": "Indirizzo, Luogo",
        "field_phone": "Telefono",
        "field_email": "E-mail",
        "field_building": "Edificio / Abitazione",
        "field_meter": "Numero punto di misura",
        "field_meter_second": "Secondo numero punto di misura (se disponibile)",
        "field_meter_pv": "Numero punto di misura (FV / immissione)",
        "subject_title": "Oggetto del contratto",
        "subject_text": (
            "Il partecipante vZEV acconsente alla partecipazione al raggruppamento virtuale per il consumo proprio "
            "(di seguito «vZEV»). Il responsabile vZEV è autorizzato a registrare e gestire il vZEV presso il "
            "gestore della rete.\n\n"
            "Il responsabile vZEV è incaricato della gestione (mutazioni, manutenzione delle tariffe, ecc.) e "
            "della puntuale emissione delle fatture elettriche.\n\n"
            "Le mutazioni (trasloco, vendita dell'immobile, ecc.) devono essere comunicate al responsabile vZEV il "
            "prima possibile, al più tardi entro 14 giorni.\n\n"
            "Il partecipante vZEV accetta di ricevere le fatture elettriche e di pagarle entro il termine convenuto."
        ),
        "agreements_title": "Accordi",
        "local_tariff_label": "Tariffa per l'energia locale ZEV",
        "local_tariff_unit": "Centesimi / kWh",
        "local_tariff_note": "Tariffa per gli anni successivi / regola",
        "local_tariff_note_placeholder": "",
        "billing_interval_label": "Intervallo di fatturazione",
        "payment_terms_label": "Condizioni di pagamento",
        "payment_terms_unit": "giorni dalla data della fattura",
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
        "sig_name": "Nome, Cognome",
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
        "contract_date": "Data di conclusione del contratto",
        "meter_hint": "Il numero del punto di misura si trova sulla fattura dell'elettricità. È composto da 33 caratteri e inizia con CH.",
    },
    "en": {
        "contract_title": "vZEV Participation Agreement",
        "parties_title": "Contracting Parties",
        "participant_label": 'Participant in the vZEV (hereinafter "vZEV Participant")',
        "owner_label": 'Responsible party for the vZEV (hereinafter "vZEV Manager")',
        "field_name": "First name, Last name",
        "field_address": "Address, City",
        "field_phone": "Phone",
        "field_email": "E-mail",
        "field_building": "Building / Unit",
        "field_meter": "Metering point number",
        "field_meter_second": "Second metering point number (if applicable)",
        "field_meter_pv": "Metering point number (PV / feed-in)",
        "subject_title": "Subject of Agreement",
        "subject_text": (
            "The vZEV Participant agrees to participate in the virtual self-consumption community "
            "(hereinafter \"vZEV\"). The vZEV Manager is authorised to register and administer the vZEV "
            "with the grid operator.\n\n"
            "The vZEV Manager is responsible for administration (mutations, tariff maintenance, etc.) and "
            "timely issuance of electricity invoices.\n\n"
            "Mutations (relocation, property sale, etc.) must be reported to the vZEV Manager as soon as "
            "possible, but no later than 14 days after the event.\n\n"
            "The vZEV Participant agrees to receive electricity invoices and to pay them within the agreed period."
        ),
        "agreements_title": "Agreements",
        "local_tariff_label": "Local ZEV Energy Tariff",
        "local_tariff_unit": "CHF cents / kWh",
        "local_tariff_note": "Tariff for following years / rule",
        "local_tariff_note_placeholder": "",
        "billing_interval_label": "Billing interval",
        "payment_terms_label": "Payment terms",
        "payment_terms_unit": "days from invoice date",
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
        "sig_name": "Last name, First name",
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
        "tariff_rp_unit": "Rp/kWh",
        "tariff_none": "—",
        "tariff_col_name": "Tariff",
        "tariff_col_price": "Price (Rp/kWh)",
        "tariff_col_calc": "Calculation",
        "contract_date": "Contract date",
        "meter_hint": "The metering point number can be found on your electricity bill. It consists of 33 characters starting with CH.",
    },
}


def _build_local_tariff_display(zev, lang: str, tr: dict) -> list[dict]:
    """Return a list of display rows for all active local energy tariffs of the ZEV.

    Each row: {"name": str, "rate_rp": str, "rate_description": str}
    For percentage-of-energy tariffs the effective price is computed from the
    active GRID energy tariffs and the calculation formula is included.
    """
    today = date.today()
    rows = []

    local_tariffs = [
        t for t in zev.tariffs.prefetch_related("periods").all()
        if (
            t.billing_mode in (BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY)
            and t.energy_type == EnergyType.LOCAL
            and t.valid_from <= today
            and (t.valid_to is None or t.valid_to >= today)
        )
    ]

    for tariff in local_tariffs:
        if tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY:
            pct = Decimal(str(tariff.percentage or 0))

            # Sum the flat / HT prices of active GRID tariffs to get the base price
            grid_tariffs = [
                t for t in zev.tariffs.prefetch_related("periods").all()
                if (
                    t.billing_mode == BillingMode.ENERGY
                    and t.energy_type == EnergyType.GRID
                    and t.valid_from <= today
                    and (t.valid_to is None or t.valid_to >= today)
                )
            ]
            grid_sum_chf = Decimal("0")
            for gt in grid_tariffs:
                periods = list(gt.periods.all())
                flat = next((p for p in periods if p.period_type == PeriodType.FLAT), None)
                if flat:
                    grid_sum_chf += Decimal(str(flat.price_chf_per_kwh))
                else:
                    ht = next((p for p in periods if p.period_type == PeriodType.HIGH), None)
                    if ht:
                        grid_sum_chf += Decimal(str(ht.price_chf_per_kwh))
                    elif periods:
                        grid_sum_chf += Decimal(str(periods[0].price_chf_per_kwh))

            effective_chf = grid_sum_chf * (pct / Decimal("100"))
            effective_rp = effective_chf * Decimal("100")
            grid_rp = grid_sum_chf * Decimal("100")
            rp_unit = tr.get("tariff_rp_unit", "Rp/kWh")

            if grid_sum_chf > 0:
                description = (
                    f"{float(pct):.2f}% × {float(grid_rp):.2f} {rp_unit}"
                    f" ({tr['tariff_pct_prefix'].strip('% ')})"
                )
            else:
                description = f"{float(pct):.2f}% {tr['tariff_pct_prefix']}"

            rows.append({
                "name": tariff.name,
                "rate_rp": f"{float(effective_rp):.2f}" if grid_sum_chf > 0 else f"{float(pct):.2f}%",
                "rate_description": description,
            })
            continue

        periods = list(tariff.periods.all())
        if not periods:
            continue

        flat = next((p for p in periods if p.period_type == PeriodType.FLAT), None)
        if flat:
            rp = float(flat.price_chf_per_kwh) * 100
            rows.append({
                "name": tariff.name,
                "rate_rp": f"{rp:.2f}",
                "rate_description": tr["tariff_flat"],
            })
        else:
            ht = next((p for p in periods if p.period_type == PeriodType.HIGH), None)
            nt = next((p for p in periods if p.period_type == PeriodType.LOW), None)
            if ht:
                rp = float(ht.price_chf_per_kwh) * 100
                rows.append({
                    "name": tariff.name,
                    "rate_rp": f"{rp:.2f}",
                    "rate_description": tr["tariff_ht"],
                })
            if nt:
                rp = float(nt.price_chf_per_kwh) * 100
                rows.append({
                    "name": tariff.name,
                    "rate_rp": f"{rp:.2f}",
                    "rate_description": tr["tariff_nt"],
                })

    return rows


def _build_contract_context(participant) -> dict:
    from zev.models import MeteringPoint, MeteringPointAssignment

    zev = participant.zev
    lang = zev.invoice_language or "de"
    tr = CONTRACT_TRANSLATIONS.get(lang, CONTRACT_TRANSLATIONS["de"])

    # ZEV owner as participant (for address details)
    owner_participant = zev.participants.filter(user=zev.owner).first()

    today = date.today()

    # Collect metering points via assignments (open or current)
    assigned_mp_ids = set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
            valid_from__lte=today,
        ).filter(
            valid_to__isnull=True
        ).values_list("metering_point_id", flat=True)
    ) | set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
            valid_from__lte=today,
            valid_to__gte=today,
        ).values_list("metering_point_id", flat=True)
    )

    all_mps = list(MeteringPoint.objects.filter(id__in=assigned_mp_ids))

    consumption_mps = [
        mp for mp in all_mps
        if mp.meter_type in (MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL)
    ]
    production_mps = [
        mp for mp in all_mps
        if mp.meter_type == MeteringPointType.PRODUCTION
    ]

    local_tariff_rows = _build_local_tariff_display(zev, lang, tr)
    billing_interval_display = tr["billing_intervals"].get(
        zev.billing_interval, zev.billing_interval
    )
    contract_date = today.strftime("%d.%m.%Y")

    return {
        "participant": participant,
        "owner_participant": owner_participant,
        "zev": zev,
        "consumption_mps": consumption_mps,
        "production_mps": production_mps,
        "local_tariff_rows": local_tariff_rows,
        "billing_interval_display": billing_interval_display,
        "contract_date": contract_date,
        "tr": tr,
        "lang": lang,
        "local_tariff_notes": zev.local_tariff_notes or "",
        "additional_contract_notes": zev.additional_contract_notes or "",
    }


def generate_contract_pdf(participant) -> bytes:
    """Generate a participation contract PDF for the given participant."""
    context = _build_contract_context(participant)
    html_string = render_to_string(CONTRACT_TEMPLATE_NAME, context)
    pdf_bytes = HTML(string=html_string, base_url=".").write_pdf()
    return pdf_bytes
