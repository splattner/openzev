"""
Contract PDF generation for ZEV participation agreements.
Renders an HTML template via Django's template engine and converts it to PDF
using WeasyPrint.
"""
import logging
from datetime import date
from decimal import Decimal

from django.template.loader import render_to_string
from django.template import Template, Context
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
        "info_title": "Informationen zum (v)ZEV",
        "info_subtitle": "Zusammenfassung der wichtigsten Regelungen für Zusammenschlüsse zum Eigenverbrauch",
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
            "gleichen Netzanschluss befinden, sondern können über das gesamte Netzgebiet desselben Netzbetreibers "
            "verteilt sein. Jeder Teilnehmer behält seinen eigenen Netzanschluss. Die Zuteilung des Eigenverbrauchs "
            "erfolgt virtuell anhand von Smart-Meter-Daten."
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
            "Jeder Teilnehmer kann mit einer Frist von zwei Monaten auf Ende einer Abrechnungsperiode austreten.",
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
            "Der Tarif für lokal produzierten Strom wird zwischen den Vertragsparteien vereinbart. "
            "Er darf gemäss Gesetz den regulären Stromtarif des Netzbetreibers (inkl. Netznutzung, "
            "Abgaben und Zuschläge) nicht überschreiten. Der Anteil Strom, der nicht lokal gedeckt werden kann, "
            "wird weiterhin zum regulären Tarif vom Netzbetreiber bezogen."
        ),
        "info_note_title": "Hinweis",
        "info_note_text": (
            "Diese Zusammenfassung dient der allgemeinen Information und ersetzt keine Rechtsberatung. "
            "Die massgeblichen gesetzlichen Bestimmungen sind verbindlich."
        ),
        "duration_title": "Vertragsdauer und Kündigung",
        "duration_text": (
            "Dieser Vertrag wird auf unbestimmte Dauer abgeschlossen und tritt mit der Unterschrift beider "
            "Parteien in Kraft. Er kann von jeder Partei mit einer Frist von zwei Monaten auf Ende einer "
            "Abrechnungsperiode schriftlich gekündigt werden."
        ),
        "jurisdiction_title": "Anwendbares Recht und Gerichtsstand",
        "jurisdiction_text": (
            "Dieser Vertrag unterliegt schweizerischem Recht. Gerichtsstand ist der Sitz des vZEV "
            "bzw. der Wohnort des vZEV-Verantwortlichen, sofern nichts anderes vereinbart wird."
        ),
        "info_privacy_title": "Datenschutz",
        "info_privacy_text": (
            "Im Rahmen des vZEV werden Smart-Meter-Daten (Stromverbrauch und -produktion) erhoben und "
            "verarbeitet. Diese Daten werden ausschliesslich für die Abrechnung der internen Stromkosten, "
            "die Ermittlung des Eigenverbrauchsanteils sowie die Verwaltung des vZEV verwendet. "
            "Die Daten werden nicht an unbefugte Dritte weitergegeben. Es gelten die Bestimmungen des "
            "Bundesgesetzes über den Datenschutz (DSG, SR 235.1)."
        ),
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
        "info_title": "Informations sur le (v)RCP",
        "info_subtitle": "Résumé des principales dispositions relatives aux regroupements pour la consommation propre",
        "info_zev_title": "Qu'est-ce qu'un RCP ?",
        "info_zev_text": (
            "Un regroupement pour la consommation propre (RCP) permet aux propriétaires fonciers d'utiliser "
            "conjointement l'électricité produite localement (p.\u202fex. à partir d'installations solaires). "
            "Les participants se trouvent au même point de raccordement au réseau. Le RCP se présente auprès du "
            "gestionnaire de réseau comme un client unique et organise la facturation interne de manière autonome."
        ),
        "info_vzev_title": "Qu'est-ce qu'un RCP virtuel (vRCP) ?",
        "info_vzev_text": (
            "Un RCP virtuel (vRCP) étend le modèle RCP : les participants n'ont plus besoin de se trouver au "
            "même point de raccordement et peuvent être répartis sur l'ensemble de la zone de desserte du même "
            "gestionnaire de réseau. Chaque participant conserve son propre raccordement. L'attribution de la "
            "consommation propre s'effectue virtuellement sur la base des données de compteurs intelligents."
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
            "Chaque participant peut se retirer moyennant un préavis de deux mois pour la fin d'une période de facturation.",
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
            "Le tarif de l'électricité produite localement est convenu entre les parties contractantes. "
            "Conformément à la loi, il ne doit pas dépasser le tarif d'électricité ordinaire du gestionnaire de "
            "réseau (y compris utilisation du réseau, taxes et suppléments). La part d'électricité qui ne peut pas "
            "être couverte localement continue d'être achetée au tarif ordinaire auprès du gestionnaire de réseau."
        ),
        "info_note_title": "Remarque",
        "info_note_text": (
            "Ce résumé est fourni à titre d'information générale et ne remplace pas un conseil juridique. "
            "Les dispositions légales applicables font foi."
        ),
        "duration_title": "Durée du contrat et résiliation",
        "duration_text": (
            "Le présent contrat est conclu pour une durée indéterminée et entre en vigueur dès la signature "
            "des deux parties. Il peut être résilié par chaque partie par écrit avec un préavis de deux mois "
            "pour la fin d'une période de facturation."
        ),
        "jurisdiction_title": "Droit applicable et for juridique",
        "jurisdiction_text": (
            "Le présent contrat est soumis au droit suisse. Le for juridique est le siège du vRCP "
            "ou le domicile du responsable du vRCP, sauf convention contraire."
        ),
        "info_privacy_title": "Protection des données",
        "info_privacy_text": (
            "Dans le cadre du vRCP, des données de compteurs intelligents (consommation et production "
            "d'électricité) sont collectées et traitées. Ces données sont utilisées exclusivement pour la "
            "facturation des coûts d'électricité internes, la détermination de la part de consommation propre "
            "et la gestion du vRCP. Les données ne sont pas transmises à des tiers non autorisés. "
            "Les dispositions de la loi fédérale sur la protection des données (LPD, RS 235.1) s'appliquent."
        ),
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
        "info_title": "Informazioni sul (v)RCP",
        "info_subtitle": "Riepilogo delle principali disposizioni relative ai raggruppamenti per il consumo proprio",
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
            "punto di allacciamento e possono essere distribuiti sull'intera zona di copertura dello stesso gestore "
            "di rete. Ogni partecipante mantiene il proprio allacciamento. L'attribuzione del consumo proprio "
            "avviene virtualmente sulla base dei dati dei contatori intelligenti."
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
            "Ogni partecipante può recedere con un preavviso di due mesi per la fine di un periodo di fatturazione.",
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
            "La tariffa per l'elettricità prodotta localmente è concordata tra le parti contraenti. "
            "Per legge non deve superare la tariffa ordinaria del gestore di rete (inclusi utilizzo della rete, "
            "tasse e supplementi). La quota di elettricità che non può essere coperta localmente continua a essere "
            "acquistata alla tariffa ordinaria dal gestore di rete."
        ),
        "info_note_title": "Avviso",
        "info_note_text": (
            "Questo riepilogo è fornito a scopo informativo generale e non sostituisce una consulenza legale. "
            "Le disposizioni di legge applicabili sono vincolanti."
        ),
        "duration_title": "Durata del contratto e disdetta",
        "duration_text": (
            "Il presente contratto è stipulato a tempo indeterminato ed entra in vigore con la firma di entrambe "
            "le parti. Può essere disdetto da ciascuna parte per iscritto con un preavviso di due mesi per la "
            "fine di un periodo di fatturazione."
        ),
        "jurisdiction_title": "Diritto applicabile e foro competente",
        "jurisdiction_text": (
            "Il presente contratto è soggetto al diritto svizzero. Il foro competente è la sede del vRCP "
            "o il domicilio del responsabile del vRCP, salvo diverso accordo."
        ),
        "info_privacy_title": "Protezione dei dati",
        "info_privacy_text": (
            "Nell'ambito del vRCP vengono raccolti e trattati dati di contatori intelligenti (consumo e produzione "
            "di elettricità). Questi dati sono utilizzati esclusivamente per la fatturazione dei costi elettrici "
            "interni, la determinazione della quota di consumo proprio e la gestione del vRCP. "
            "I dati non vengono trasmessi a terzi non autorizzati. Si applicano le disposizioni della "
            "legge federale sulla protezione dei dati (LPD, RS 235.1)."
        ),
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
        "info_title": "Information on (v)ZEV",
        "info_subtitle": "Summary of the key regulations for self-consumption communities in Switzerland",
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
            "connection point and can be distributed across the entire service area of the same grid operator. "
            "Each participant retains their own grid connection. Self-consumption allocation is performed "
            "virtually based on smart meter data."
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
            "Each participant may withdraw with two months' notice at the end of a billing period.",
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
            "The tariff for locally produced electricity is agreed between the contracting parties. "
            "By law, it must not exceed the regular electricity tariff of the grid operator (including grid usage, "
            "levies, and surcharges). Any electricity that cannot be covered locally continues to be purchased "
            "at the regular tariff from the grid operator."
        ),
        "info_note_title": "Disclaimer",
        "info_note_text": (
            "This summary is provided for general information purposes and does not constitute legal advice. "
            "The applicable statutory provisions are authoritative."
        ),
        "duration_title": "Contract duration and termination",
        "duration_text": (
            "This agreement is concluded for an indefinite period and takes effect upon signature by both "
            "parties. It may be terminated by either party in writing with two months' notice at the end "
            "of a billing period."
        ),
        "jurisdiction_title": "Governing law and jurisdiction",
        "jurisdiction_text": (
            "This agreement is governed by Swiss law. The place of jurisdiction is the registered seat "
            "of the vZEV or the domicile of the vZEV manager, unless otherwise agreed."
        ),
        "info_privacy_title": "Data protection",
        "info_privacy_text": (
            "Within the vZEV, smart meter data (electricity consumption and production) is collected and "
            "processed. This data is used exclusively for billing internal electricity costs, determining "
            "the self-consumption share, and administering the vZEV. Data is not disclosed to unauthorised "
            "third parties. The provisions of the Federal Act on Data Protection (FADP, SR 235.1) apply."
        ),
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

    # Include all non-ended assignments so the contract can be prefilled for
    # participants who start on a future meter assignment.
    assigned_mp_ids = set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
        ).filter(
            valid_to__isnull=True,
        ).values_list("metering_point_id", flat=True)
    ) | set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
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
    # Import here to avoid circular imports at module load time
    from .models import PdfTemplate
    record = PdfTemplate.objects.filter(template_name=CONTRACT_TEMPLATE_NAME).first()
    if record:
        html_string = Template(record.content).render(Context(context))
    else:
        html_string = render_to_string(CONTRACT_TEMPLATE_NAME, context)
    pdf_bytes = HTML(string=html_string, base_url=".").write_pdf()
    return pdf_bytes
