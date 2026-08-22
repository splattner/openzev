import type { ReactElement } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import type { UserRole } from '../types/api'

export function ProtectedRoute({
    children,
    allowedRoles,
}: {
    children: ReactElement
    allowedRoles?: UserRole[]
}) {
    const { t } = useTranslation()
    const { isAuthenticated, isLoading, user, isImpersonating } = useAuth()
    const location = useLocation()

    if (isLoading) {
        return <div className="center-screen">{t('common.loading')}</div>
    }

    if (!isAuthenticated) {
        return <Navigate to="/login" replace />
    }

    if (user?.must_change_password && !isImpersonating && location.pathname !== '/account') {
        return <Navigate to="/account" replace state={{ forcePasswordChange: true }} />
    }

    if (allowedRoles && (!user || !allowedRoles.includes(user.role))) {
        return <Navigate to="/" replace />
    }

    return children
}
