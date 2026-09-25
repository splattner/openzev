"""The ``invoice_pdfs`` transfer-archive section (format version 3).

Opt-in and dependent on ``invoices`` (an invoice's PDF means nothing without
the invoice it belongs to). The member name is a deterministic function of
``invoice_number`` (``pdf_member_name`` in ``export.py``, mirroring
``_reading_csv_name``'s reasoning) rather than something read from the
manifest, so the round-trip tests here also stand in as tests of that
function agreeing with itself on both sides.
"""
import io
import json
import zipfile

from django.core.files.base import ContentFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice, InvoicePdfStatus
from testing.helpers import authenticate as auth, make_user
from zev.transfer import ImportFailed, import_archive
from zev.transfer.export import pdf_member_name
from zev.transfer.schema import FORMAT_VERSION, SECTIONS, SUPPORTED_FORMAT_VERSIONS

from .test_transfer import build_populated_zev, export_and_clear, export_to_bytes, rewrite_archive

ZEV_URL = "/api/v1/zev/zevs"


def _attach_pdf(invoice, content=b"%PDF-1.4 fake invoice"):
    invoice.pdf_file.save(f"invoice_{invoice.invoice_number}.pdf", ContentFile(content), save=False)
    Invoice.objects.filter(pk=invoice.pk).update(
        pdf_file=invoice.pdf_file.name, pdf_status=InvoicePdfStatus.READY,
    )
    invoice.refresh_from_db()
    return invoice


class FormatVersionTests(TestCase):
    def test_format_version_is_4(self):
        self.assertEqual(FORMAT_VERSION, 4)

    def test_versions_1_through_3_remain_supported(self):
        self.assertEqual(SUPPORTED_FORMAT_VERSIONS, frozenset({1, 2, 3, 4}))

    def test_invoice_pdfs_is_a_known_section_depending_on_invoices(self):
        from zev.transfer.schema import SECTION_DEPENDENCIES, SECTION_INVOICE_PDFS, SECTION_INVOICES

        self.assertIn(SECTION_INVOICE_PDFS, SECTIONS)
        self.assertEqual(SECTION_DEPENDENCIES[SECTION_INVOICE_PDFS], (SECTION_INVOICES,))


class MemberNamingTests(TestCase):
    def test_deterministic_and_collision_safe(self):
        """Same construction, same reason, as the reading-CSV member name:
        distinct numbers that sanitise to the same string must not collide."""
        self.assertEqual(pdf_member_name("INV-00001"), pdf_member_name("INV-00001"))
        self.assertNotEqual(pdf_member_name("INV/00001"), pdf_member_name("INV_00001"))

    def test_stays_under_the_invoices_pdf_directory(self):
        self.assertTrue(pdf_member_name("INV-00001").startswith("invoices/pdf/"))
        self.assertTrue(pdf_member_name("INV-00001").endswith(".pdf"))


class RoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pdf_owner", UserRole.ZEV_OWNER)
        cls.importer = make_user("pdf_importer", UserRole.ADMIN)

    def _zev_with_pdf_invoice(self, *, meter_prefix):
        zev = build_populated_zev(self.owner, name="PDF ZEV", meter_prefix=meter_prefix)
        invoice = Invoice.objects.get(zev=zev)
        _attach_pdf(invoice, content=b"%PDF-1.4 the real bytes")
        return zev, invoice

    def test_pdf_travels_when_the_section_is_selected(self):
        zev, invoice = self._zev_with_pdf_invoice(meter_prefix="RTP")
        raw = export_and_clear(zev, ["zev", "participants", "invoices", "invoice_pdfs"])

        result = import_archive(io.BytesIO(raw), owner=self.importer)
        imported = Invoice.objects.get(zev_id=result["zev_id"], invoice_number=invoice.invoice_number)

        self.assertTrue(imported.pdf_file.name)
        self.assertEqual(imported.pdf_status, InvoicePdfStatus.READY)
        with imported.pdf_file.open("rb") as f:
            self.assertEqual(f.read(), b"%PDF-1.4 the real bytes")
        self.assertEqual(result["counts"]["invoice_pdfs"], 1)

    def test_pdf_does_not_travel_when_the_section_is_not_selected(self):
        zev, invoice = self._zev_with_pdf_invoice(meter_prefix="RTN")
        raw = export_and_clear(zev, ["zev", "participants", "invoices"])

        result = import_archive(io.BytesIO(raw), owner=self.importer)
        imported = Invoice.objects.get(zev_id=result["zev_id"], invoice_number=invoice.invoice_number)

        self.assertFalse(imported.pdf_file)
        self.assertEqual(imported.pdf_status, InvoicePdfStatus.NONE)
        self.assertNotIn("invoice_pdfs", result["counts"])

    def test_an_invoice_with_no_pdf_contributes_no_member_and_is_unaffected(self):
        zev = build_populated_zev(self.owner, name="No-PDF ZEV", meter_prefix="NOP")
        invoice = Invoice.objects.get(zev=zev)
        self.assertFalse(invoice.pdf_file)
        raw = export_and_clear(zev, ["zev", "participants", "invoices", "invoice_pdfs"])

        result = import_archive(io.BytesIO(raw), owner=self.importer)
        imported = Invoice.objects.get(zev_id=result["zev_id"], invoice_number=invoice.invoice_number)

        self.assertFalse(imported.pdf_file)
        self.assertEqual(result["counts"]["invoice_pdfs"], 0)

    def test_selecting_invoice_pdfs_without_invoices_is_refused(self):
        zev, _invoice = self._zev_with_pdf_invoice(meter_prefix="DEP")
        with self.assertRaises(ValueError) as ctx:
            export_to_bytes(zev, ["zev", "invoice_pdfs"])
        self.assertIn("invoice_pdfs requires invoices", str(ctx.exception))

    def test_v1_and_v2_archives_without_the_section_still_import(self):
        """Backward compatibility: an archive written before this section
        existed has no invoices/pdf/ members and must still import cleanly."""
        zev = build_populated_zev(self.owner, name="Legacy ZEV", meter_prefix="LEG")
        raw = export_and_clear(zev, ["zev", "participants", "invoices"])
        raw = rewrite_archive(raw, replace={"manifest.json": _legacy_manifest(raw, version=2)})

        result = import_archive(io.BytesIO(raw), owner=self.importer)
        self.assertEqual(result["counts"]["invoices"], 1)


def _legacy_manifest(raw, *, version):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["format_version"] = version
    return manifest


class ManifestVerificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pdf_verify_owner", UserRole.ZEV_OWNER)
        cls.importer = make_user("pdf_verify_importer", UserRole.ADMIN)

    def test_a_dropped_pdf_member_is_reported_not_silently_missing(self):
        """The manifest still declares one invoice_pdfs count, but the member
        that would satisfy it is gone — _verify_manifest_counts must catch
        the shortfall rather than the import quietly producing zero."""
        zev = build_populated_zev(self.owner, name="Verify ZEV", meter_prefix="VER")
        invoice = Invoice.objects.get(zev=zev)
        _attach_pdf(invoice)
        raw = export_and_clear(zev, ["zev", "participants", "invoices", "invoice_pdfs"])
        member = pdf_member_name(invoice.invoice_number)
        tampered = rewrite_archive(raw, drop=(member,))

        with self.assertRaises(ImportFailed) as ctx:
            import_archive(io.BytesIO(tampered), owner=self.importer)
        matches = [e for e in ctx.exception.errors if e["section"] == "invoice_pdfs"]
        self.assertEqual(len(matches), 1)
        self.assertIn("declares 1 invoice_pdf", json.dumps(matches[0]["errors"]))


class TransferEndpointInvoicePdfTests(TestCase):
    """The section reaches end to end through the real view, not just the
    library functions above."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pdf_ep_owner", UserRole.ZEV_OWNER)
        cls.admin = make_user("pdf_ep_admin", UserRole.ADMIN)

    def setUp(self):
        self.client = APIClient()

    def test_transfer_sections_lists_invoice_pdfs(self):
        auth(self.client, self.owner)
        response = self.client.get(f"{ZEV_URL}/transfer-sections/")
        self.assertEqual(response.status_code, 200, response.content)
        names = [entry["name"] for entry in response.json()["sections"]]
        self.assertIn("invoice_pdfs", names)

    def test_export_with_invoice_pdfs_contains_the_pdf_member(self):
        zev = build_populated_zev(self.owner, name="Endpoint ZEV", meter_prefix="EPT")
        invoice = Invoice.objects.get(zev=zev)
        _attach_pdf(invoice)
        auth(self.client, self.owner)

        response = self.client.get(
            f"{ZEV_URL}/{zev.id}/export/?sections=zev,participants,invoices,invoice_pdfs"
        )
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertIn(pdf_member_name(invoice.invoice_number), archive.namelist())
