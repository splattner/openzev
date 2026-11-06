from invoices.models import ContractIssue
from inbox.services import deliver
from inbox.models import DocumentKind

PDF = b"%PDF-1.4\n%delivered\n"


def make_contract_issue(participant, owner, version=1):
    return ContractIssue.objects.create(
        zev=participant.zev, participant=participant, version=version, document_number=f"C-{version}",
        language="de", context_hash="c" * 64, pdf=b"%PDF-contract", issued_by=owner,
    )


def deliver_operator_document(participant, title="ZEV rules", body=PDF, **kwargs):
    document, _ = deliver(participant=participant, kind=DocumentKind.OPERATOR, title=title, body=body, **kwargs)
    return document
