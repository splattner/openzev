import { useAuth } from '../lib/auth'
import { DashboardPage } from './DashboardPage'
import { OverviewPage } from './OverviewPage'

/** Role-aware start page: operational work for managers, the existing
 * personal dashboard for participants. */
export function HomePage() {
    const { user } = useAuth()
    const canManage = user?.role === 'admin' || user?.role === 'zev_owner'

    return canManage ? <OverviewPage /> : <DashboardPage />
}
