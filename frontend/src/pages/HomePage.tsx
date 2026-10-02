import { useCommunityAccess } from '../lib/communityAccess'
import { DashboardPage } from './DashboardPage'
import { OverviewPage } from './OverviewPage'

/** Start page by the account's relation to the selected community (#761):
 * operational work for admins, managers and viewers, the personal dashboard
 * for participants. */
export function HomePage() {
    const { isZevScope } = useCommunityAccess()

    return isZevScope ? <OverviewPage /> : <DashboardPage />
}
