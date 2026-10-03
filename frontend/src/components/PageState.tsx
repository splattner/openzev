import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { PageSkeleton, type PageSkeletonVariant } from './PageSkeleton'
import { Notice } from './Notice'

export type PageStateProps = {
    isLoading?: boolean
    isError?: boolean
    /** Content shown on error; defaults to common.error. */
    error?: ReactNode
    onRetry?: () => void
    isRetrying?: boolean
    skeleton?: PageSkeletonVariant
    children: ReactNode
}

/** Blocking error, then initial loading, then content. Pages own their empty states. */
export function PageState({
    isLoading,
    isError,
    error,
    onRetry,
    isRetrying,
    skeleton = 'card',
    children,
}: PageStateProps) {
    const { t } = useTranslation()
    if (isError) {
        return <Notice tone="error" onRetry={onRetry} isRetrying={isRetrying}>{error ?? t('common.error')}</Notice>
    }
    if (isLoading) {
        return <PageSkeleton variant={skeleton} />
    }
    return <>{children}</>
}
