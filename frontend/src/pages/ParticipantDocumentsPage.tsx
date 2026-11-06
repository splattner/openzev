import { useTranslation } from 'react-i18next'
import { Outbox } from '../features/inbox/Outbox'
import { PageHeader } from '../components/PageHeader'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'

/**
 * What the community delivered to its participants, and where to issue or upload a document
 * (`/documents`, SPEC-2026-11-participant-document-inbox §7.2). A page of its own rather than a
 * billing tab: it is not about invoices, and hidden behind a tab nobody found it.
 */
export function ParticipantDocumentsPage() {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { selectedZev } = useManagedZev()
    const { canWriteSelectedCommunity } = useCommunityAccess()

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('nav.documents')}
                description={t(canWriteSelectedCommunity ? 'pages.participantDocuments.description' : 'pages.participantDocuments.descriptionReadOnly')}
            />
            <Outbox />
        </div>
    )
}
