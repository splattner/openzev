import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useCommunityAccess } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { EmptyState } from './EmptyState'
import { Notice } from './Notice'
import { PageSkeleton, type PageSkeletonVariant } from './PageSkeleton'

export type ScopeGuardProps = {
    children: ReactNode
    skeleton?: PageSkeletonVariant
}

/**
 * Gates community management content on a resolved ZEV. Cached scope remains
 * usable after a failed refetch. Participant views pass through.
 */
export function ScopeGuard({ children, skeleton = 'cardList' }: ScopeGuardProps) {
    const { t } = useTranslation()
    const { isAdmin, isZevScope, shellRole } = useCommunityAccess()
    const { isLoading, isError, isFetching, refetch, selectedZevId, selectedZev } = useManagedZev()

    if (!isZevScope && shellRole !== 'none') {
        return <>{children}</>
    }

    const hasScope = Boolean(selectedZevId && selectedZev?.id === selectedZevId)
    if (!hasScope && isLoading) {
        return <PageSkeleton variant={skeleton} />
    }

    const failure = isError ? (
        <Notice tone={hasScope ? 'warning' : 'error'} onRetry={refetch} isRetrying={isFetching}>
            {t(hasScope ? 'common.scopeGuard.refreshFailed' : 'common.scopeGuard.loadFailed')}
        </Notice>
    ) : null

    if (hasScope) {
        return <>{failure}{children}</>
    }

    if (failure) return failure

    return isAdmin ? (
        <EmptyState
            titleKey="pages.zevs.emptyState.title"
            descriptionKey="pages.zevs.emptyState.description"
            actions={[{ labelKey: 'pages.zevs.emptyState.createAction', to: '/admin/zevs' }]}
        />
    ) : (
        <EmptyState
            titleKey="pages.guest.title"
            descriptionKey="pages.guest.description"
            actions={[{ labelKey: 'pages.guest.accountLink', to: '/account', variant: 'secondary' }]}
        />
    )
}
