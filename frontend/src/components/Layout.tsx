import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { fetchUsers } from '../lib/api'
import { LanguageSelector } from './LanguageSelector'

export function Layout() {
    const { t } = useTranslation()
    const { user, logout, isImpersonating, impersonator, stopImpersonation } = useAuth()
    const { managedZevs, selectedZevId, selectedZev, isSelectable, isLoading: managedZevLoading, setSelectedZevId } = useManagedZev()
    const usersQuery = useQuery({
        queryKey: ['users'],
        queryFn: fetchUsers,
        enabled: user?.role === 'admin',
    })
    const location = useLocation()
    const navigate = useNavigate()
    const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
    const [isZevMenuOpen, setIsZevMenuOpen] = useState(false)
    const [isStoppingImpersonation, setIsStoppingImpersonation] = useState(false)
    const [isManageNavOpen, setIsManageNavOpen] = useState(
        location.pathname.startsWith('/participants') ||
        location.pathname.startsWith('/zev-settings') ||
        location.pathname.startsWith('/metering-points') ||
        location.pathname.startsWith('/metering-data') ||
        location.pathname.startsWith('/admin/zevs'),
    )
    const [isAdminNavOpen, setIsAdminNavOpen] = useState(location.pathname.startsWith('/admin'))
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
        if (typeof window === 'undefined') {
            return false
        }
        return window.localStorage.getItem('openzev.sidebarCollapsed') === 'true'
    })
    const userMenuRef = useRef<HTMLDivElement | null>(null)
    const zevMenuRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (location.pathname.startsWith('/admin')) {
            setIsAdminNavOpen(true)
        }
        if (
            location.pathname.startsWith('/participants') ||
            location.pathname.startsWith('/zev-settings') ||
            location.pathname.startsWith('/metering-points') ||
            location.pathname.startsWith('/metering-data') ||
            location.pathname.startsWith('/admin/zevs')
        ) {
            setIsManageNavOpen(true)
        }
    }, [location.pathname])

    useEffect(() => {
        window.localStorage.setItem('openzev.sidebarCollapsed', String(isSidebarCollapsed))
    }, [isSidebarCollapsed])

    useEffect(() => {
        function handleOutsideClick(event: MouseEvent) {
            if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
                setIsUserMenuOpen(false)
            }
            if (zevMenuRef.current && !zevMenuRef.current.contains(event.target as Node)) {
                setIsZevMenuOpen(false)
            }
        }

        document.addEventListener('mousedown', handleOutsideClick)
        return () => document.removeEventListener('mousedown', handleOutsideClick)
    }, [])

    const displayName = `${user?.first_name ?? ''} ${user?.last_name ?? ''}`.trim() || user?.username || ''
    const canManage = user?.role === 'admin' || user?.role === 'zev_owner'
    const adminIsActive = location.pathname.startsWith('/admin')
    const manageIsActive =
        location.pathname.startsWith('/participants') ||
        location.pathname.startsWith('/zev-settings') ||
        location.pathname.startsWith('/metering-points') ||
        location.pathname.startsWith('/metering-data') ||
        location.pathname.startsWith('/admin/zevs')

    const ownerById = new Map((usersQuery.data?.results ?? []).map((candidate) => [candidate.id, candidate]))
    const selectedZevOwner = selectedZev ? ownerById.get(selectedZev.owner) : undefined
    const effectiveOwner = selectedZevOwner ?? (user?.role === 'zev_owner' ? user : undefined)
    const selectedZevOwnerName = effectiveOwner
        ? `${effectiveOwner.first_name} ${effectiveOwner.last_name}`.trim() || effectiveOwner.username
        : '-'

    return (
        <div className={`shell${isSidebarCollapsed ? ' shell-collapsed' : ''}`}>
            <aside className={`sidebar${isSidebarCollapsed ? ' collapsed' : ''}`}>
                <div className="sidebar-top">
                    <div className="sidebar-brand-row">
                        <div className="sidebar-brand">
                            <img
                                src="/openzevlogo_darkbg.png"
                                alt={t('app.title')}
                                className="sidebar-logo"
                            />
                        </div>
                        <button
                            type="button"
                            className="sidebar-collapse-button"
                            onClick={() => setIsSidebarCollapsed((prev) => !prev)}
                            aria-label={isSidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
                            title={isSidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
                        >
                            <ChevronIcon direction={isSidebarCollapsed ? 'right' : 'left'} />
                        </button>
                    </div>

                    <nav className="nav-list">
                        <NavLink
                            to="/"
                            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                            title={t('nav.dashboard')}
                        >
                            <span className="nav-icon"><DashboardIcon /></span>
                            <span className="nav-label">{t('nav.dashboard')}</span>
                        </NavLink>

                        {canManage && (
                            <div className="nav-section">
                                {isSidebarCollapsed ? (
                                    <NavLink
                                        to="/participants"
                                        className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                                        title="Manage (v)Zev"
                                    >
                                        <span className="nav-icon"><BuildingIcon /></span>
                                        <span className="nav-label">Manage (v)Zev</span>
                                    </NavLink>
                                ) : (
                                    <>
                                        <button
                                            type="button"
                                            className={`nav-toggle${manageIsActive ? ' active' : ''}`}
                                            onClick={() => setIsManageNavOpen((prev) => !prev)}
                                            title="Manage (v)Zev"
                                        >
                                            <span className="nav-toggle-main">
                                                <span className="nav-icon"><BuildingIcon /></span>
                                                <span className="nav-label">Manage (v)Zev</span>
                                            </span>
                                            <span className="nav-caret" aria-hidden="true">{isManageNavOpen ? '−' : '+'}</span>
                                        </button>
                                        {isManageNavOpen && (
                                            <div className="nav-sublist">
                                                <NavLink to="/participants" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title={t('nav.participants')}>
                                                    <span className="nav-icon"><UsersIcon /></span>
                                                    <span className="nav-label">{t('nav.participants')}</span>
                                                </NavLink>

                                                <NavLink to="/metering-points" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title={t('nav.meteringPoints')}>
                                                    <span className="nav-icon"><PlugIcon /></span>
                                                    <span className="nav-label">{t('nav.meteringPoints')}</span>
                                                </NavLink>
                                                <NavLink to="/metering-data" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title={t('nav.meteringData')}>
                                                    <span className="nav-icon"><ChartIcon /></span>
                                                    <span className="nav-label">{t('nav.meteringData')}</span>
                                                </NavLink>
                                                <NavLink to="/zev-settings" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title="Settings">
                                                    <span className="nav-icon"><SettingsIcon /></span>
                                                    <span className="nav-label">Settings</span>
                                                </NavLink>
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        )}

                        {canManage && (
                            <NavLink
                                to="/tariffs"
                                className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                                title={t('nav.tariffs')}
                            >
                                <span className="nav-icon"><TagIcon /></span>
                                <span className="nav-label">{t('nav.tariffs')}</span>
                            </NavLink>
                        )}

                        {canManage && (
                            <NavLink
                                to="/invoices"
                                className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                                title={t('nav.invoices')}
                            >
                                <span className="nav-icon"><InvoiceIcon /></span>
                                <span className="nav-label">{t('nav.invoices')}</span>
                            </NavLink>
                        )}

                        {canManage && (
                            <NavLink
                                to="/imports"
                                className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                                title={t('nav.imports')}
                            >
                                <span className="nav-icon"><ImportIcon /></span>
                                <span className="nav-label">{t('nav.imports')}</span>
                            </NavLink>
                        )}

                        {user?.role === 'admin' && (
                            <div className="nav-section nav-section-end">
                                {isSidebarCollapsed ? (
                                    <NavLink
                                        to="/admin"
                                        className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                                        title={t('nav.adminConsole')}
                                    >
                                        <span className="nav-icon"><SettingsIcon /></span>
                                        <span className="nav-label">{t('nav.adminConsole')}</span>
                                    </NavLink>
                                ) : (
                                    <>
                                        <button
                                            type="button"
                                            className={`nav-toggle${adminIsActive ? ' active' : ''}`}
                                            onClick={() => setIsAdminNavOpen((prev) => !prev)}
                                            title={t('nav.adminConsole')}
                                        >
                                            <span className="nav-toggle-main">
                                                <span className="nav-icon"><SettingsIcon /></span>
                                                <span className="nav-label">{t('nav.adminConsole')}</span>
                                            </span>
                                            <span className="nav-caret" aria-hidden="true">{isAdminNavOpen ? '−' : '+'}</span>
                                        </button>
                                        {isAdminNavOpen && (
                                            <div className="nav-sublist">
                                                <NavLink to="/admin" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title={t('nav.adminOverview')}>
                                                    <span className="nav-icon"><OverviewIcon /></span>
                                                    <span className="nav-label">{t('nav.adminOverview')}</span>
                                                </NavLink>
                                                <NavLink to="/admin/zevs" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title={t('nav.zevs')}>
                                                    <span className="nav-icon"><BuildingIcon /></span>
                                                    <span className="nav-label">{t('nav.zevs')}</span>
                                                </NavLink>
                                                <NavLink to="/admin/accounts" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title="Accounts & Participants">
                                                    <span className="nav-icon"><UsersIcon /></span>
                                                    <span className="nav-label">Accounts & Participants</span>
                                                </NavLink>
                                                <NavLink to="/admin/settings/regional" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title="Regional Settings">
                                                    <span className="nav-icon"><SettingsIcon /></span>
                                                    <span className="nav-label">Regional Settings</span>
                                                </NavLink>
                                                <NavLink to="/admin/pdf-templates" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} title={t('nav.adminPdfTemplates')}>
                                                    <span className="nav-icon"><PdfIcon /></span>
                                                    <span className="nav-label">{t('nav.adminPdfTemplates')}</span>
                                                </NavLink>
                                            </div>
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </nav>
                </div>
            </aside>

            <main className="content">
                <header className="top-nav">
                    {isImpersonating && impersonator && (
                        <div className="impersonation-banner" role="status" aria-live="polite">
                            <span>
                                Impersonating account as <strong>{displayName || user?.username}</strong>
                            </span>
                            <button
                                type="button"
                                className="button button-secondary"
                                disabled={isStoppingImpersonation}
                                onClick={async () => {
                                    try {
                                        setIsStoppingImpersonation(true)
                                        await stopImpersonation()
                                        navigate('/admin/accounts')
                                    } finally {
                                        setIsStoppingImpersonation(false)
                                    }
                                }}
                            >
                                Stop
                            </button>
                        </div>
                    )}

                    {canManage && (
                        <div className="user-menu zev-menu" ref={zevMenuRef}>
                            <button
                                type="button"
                                className="user-menu-trigger"
                                onClick={() => setIsZevMenuOpen((prev) => !prev)}
                            >
                                <span className="user-avatar" aria-hidden="true">🏢</span>
                                <span className="user-meta">
                                    <strong>{selectedZev?.name || 'No (v)ZEV selected'}</strong>
                                    <small>{selectedZevOwnerName} · {effectiveOwner?.email || '-'}</small>
                                </span>
                            </button>

                            {isZevMenuOpen && (
                                <div className="user-menu-dropdown zev-menu-dropdown">
                                    <div className="user-menu-section">
                                        <div className="user-menu-section-title">Selecte (v)ZEV to manage</div>
                                        <div className="zev-dropdown-list" role="listbox" aria-label="Select (v)ZEV">
                                            {managedZevLoading ? (
                                                <div className="zev-dropdown-item zev-dropdown-item-muted">Loading…</div>
                                            ) : managedZevs.length === 0 ? (
                                                <div className="zev-dropdown-item zev-dropdown-item-muted">No (v)ZEV available</div>
                                            ) : (
                                                managedZevs.map((zev) => {
                                                    const isSelected = zev.id === selectedZevId
                                                    return (
                                                        <button
                                                            key={zev.id}
                                                            type="button"
                                                            className={`zev-dropdown-item${isSelected ? ' active' : ''}`}
                                                            onClick={() => {
                                                                if (isSelectable) {
                                                                    setSelectedZevId(zev.id)
                                                                }
                                                                setIsZevMenuOpen(false)
                                                            }}
                                                            disabled={!isSelectable && !isSelected}
                                                            aria-selected={isSelected}
                                                        >
                                                            {zev.name}
                                                        </button>
                                                    )
                                                })
                                            )}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="user-menu" ref={userMenuRef}>
                        <button
                            type="button"
                            className="user-menu-trigger"
                            onClick={() => setIsUserMenuOpen((prev) => !prev)}
                        >
                            <span className="user-avatar" aria-hidden="true">👤</span>
                            <span className="user-meta">
                                <strong>{displayName}</strong>
                                <small>{user?.email}</small>
                            </span>
                        </button>

                        {isUserMenuOpen && (
                            <div className="user-menu-dropdown">
                                <NavLink
                                    to="/account"
                                    className="user-menu-item"
                                    onClick={() => setIsUserMenuOpen(false)}
                                >
                                    <span className="user-menu-item-icon"><AccountIcon /></span>
                                    {t('account.title')}
                                </NavLink>
                                <div className="user-menu-section">
                                    <div className="user-menu-section-title">{t('common.language')}</div>
                                    <LanguageSelector variant="menu" />
                                </div>
                                <button
                                    type="button"
                                    className="user-menu-item"
                                    onClick={logout}
                                >
                                    <span className="user-menu-item-icon"><LogoutIcon /></span>
                                    {t('nav.logout')}
                                </button>
                            </div>
                        )}
                    </div>
                </header>
                <Outlet />
            </main>
        </div>
    )
}

function DashboardIcon() {
    return <IconSvg path="M3 12.75 12 4l9 8.75V21a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
}

function BuildingIcon() {
    return <IconSvg path="M4 21V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v16m-8-12h2m-2 4h2m-2 4h2m4-8h2m-2 4h2m-2 4h2M3 21h18" />
}

function UsersIcon() {
    return <IconSvg path="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2m18 0v-2a4 4 0 0 0-3-3.87M14 4.13a4 4 0 0 1 0 7.75M9.5 11A4 4 0 1 0 9.5 3a4 4 0 0 0 0 8Z" />
}

function PlugIcon() {
    return <IconSvg path="M9 7V3m6 4V3m-7 8h8a2 2 0 0 0 2-2V7H6v2a2 2 0 0 0 2 2Zm4 0v6a4 4 0 0 1-4 4h-1" />
}

function ChartIcon() {
    return <IconSvg path="M4 19V5m0 14h16M8 17v-5m4 5V8m4 9V11" />
}

function TagIcon() {
    return <IconSvg path="m20.59 13.41-7.18 7.18a2 2 0 0 1-2.83 0L3 13V3h10l7.59 7.59a2 2 0 0 1 0 2.82ZM7.5 7.5h.01" />
}

function InvoiceIcon() {
    return <IconSvg path="M7 3h8l4 4v14l-2-1-2 1-2-1-2 1-2-1-2 1V4a1 1 0 0 1 1-1Zm1 6h8m-8 4h8m-8 4h5" />
}

function ImportIcon() {
    return <IconSvg path="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
}

function SettingsIcon() {
    return <IconSvg path="M12 8.5A3.5 3.5 0 1 1 8.5 12 3.5 3.5 0 0 1 12 8.5Zm7 3.5.94-.54-1-1.73-1.07.18a6.97 6.97 0 0 0-1.2-1.2l.18-1.07-1.73-1-.54.94a6.97 6.97 0 0 0-1.55-.42L12.5 4h-2l-.53 1.16a6.97 6.97 0 0 0-1.55.42l-.54-.94-1.73 1 .18 1.07a6.97 6.97 0 0 0-1.2 1.2l-1.07-.18-1 1.73.94.54a6.97 6.97 0 0 0 0 1.84l-.94.54 1 1.73 1.07-.18c.33.45.74.86 1.2 1.2l-.18 1.07 1.73 1 .54-.94c.49.2 1.01.34 1.55.42L10.5 20h2l.53-1.16c.54-.08 1.06-.22 1.55-.42l.54.94 1.73-1-.18-1.07c.45-.33.86-.74 1.2-1.2l1.07.18 1-1.73-.94-.54a6.97 6.97 0 0 0 0-1.84Z" />
}

function OverviewIcon() {
    return <IconSvg path="M4 4h7v7H4zm9 0h7v4h-7zM4 13h4v7H4zm6 3h10v4H10z" />
}

function PdfIcon() {
    return <IconSvg path="M7 3h8l4 4v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm1 14h2.5a2.5 2.5 0 0 0 0-5H8Zm1.5-3.5h1a1 1 0 1 1 0 2h-1Zm5.5-1.5h-3v5h1.5v-1.75h1.25M13.5 13.5h1.5m-1.5 2h1.25" />
}

function AccountIcon() {
    return <IconSvg path="M20 21a8 8 0 0 0-16 0m8-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
}

function LogoutIcon() {
    return <IconSvg path="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9" />
}

function ChevronIcon({ direction }: { direction: 'left' | 'right' }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {direction === 'left' ? <path d="m15 18-6-6 6-6" /> : <path d="m9 18 6-6-6-6" />}
        </svg>
    )
}

function IconSvg({ path }: { path: string | ReactNode }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {typeof path === 'string' ? <path d={path} /> : path}
        </svg>
    )
}
