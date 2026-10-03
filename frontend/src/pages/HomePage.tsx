import { useCommunityAccess } from '../lib/communityAccess'
import { Navigate } from 'react-router-dom'
import { DashboardPage } from './DashboardPage'
import { GuestHomePage } from './GuestHomePage'
import { OverviewPage } from './OverviewPage'

/** Start page by the account's relation to the selected community (#761):
 * operational work for admins, managers and viewers, the personal dashboard
 * for participants, and a linking explanation for accounts without access. */
export function HomePage() {
    const { isZevScope, shellRole } = useCommunityAccess()

    if (shellRole === 'former') return <Navigate to="/me/invoices" replace />

    if (isZevScope) return <OverviewPage />
    if (shellRole === 'none') return <GuestHomePage />
    return <DashboardPage />
}
