import { useTranslation } from 'react-i18next'
import { PageHeader } from '../components/PageHeader'
import { ScopeGuard } from '../components/ScopeGuard'
import { LiveEnergyView } from '../features/live/LiveEnergyView'
import { useScopeNote } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { selectedCommunityName } from '../lib/membership'

/**
 * Live energy (`/live`): what the community produces and uses right now, from the live sources
 * (SPEC-2026-live-energy-data §7.1). The only page that polls the live endpoints.
 */
export function LivePage() {
    const { t } = useTranslation()
    const { selectedZevId, selectedZev, entries } = useManagedZev()
    const scopeNote = useScopeNote()

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedCommunityName({ selectedZev, entries, selectedZevId })}
                scopeNote={scopeNote}
                title={t('pages.live.title')}
                description={t('pages.live.description')}
            />
            <ScopeGuard skeleton="kpiRow">
                <LiveEnergyView zevId={selectedZevId || undefined} />
            </ScopeGuard>
        </div>
    )
}
