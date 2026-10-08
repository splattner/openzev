import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useMediaQuery } from '@mantine/hooks'
import { Link, NavLink, Outlet, matchPath, useLocation, useMatch, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess } from '../lib/communityAccess'
import { fetchFeasibilityCalculatorEnabled } from '../lib/api/feasibility'
import { queryKeys } from '../lib/api/queryKeys'
import { apiErrorPayload } from '../lib/api/errors'
import { LanguageSelector } from './LanguageSelector'
import { ConfirmDialog, useConfirmDialog } from './ConfirmDialog'
import { hasUnsavedZevSettingsDraft } from '../lib/zevUnsavedGuard'
import { useToast } from '../lib/toast'
import { useRouteFocus } from '../lib/useRouteFocus'
import pkg from '../../package.json'

// Keep in sync with the mobile shell breakpoint in index.css.
const MOBILE_MEDIA_QUERY = '(max-width: 768px)'

function SidebarLink({ to, label, icon, active, end, className, scope, collapsed }: {
    to: string
    label: string
    icon: ReactNode
    active?: boolean
    end?: boolean
    className?: string
    scope?: string
    collapsed: boolean
}) {
    const { t } = useTranslation()
    // Link, not NavLink: active state is computed here to control class + aria-current.
    const { pathname } = useLocation()
    const isActive = active ?? matchPath({ path: to, end: end ?? to === '/' }, pathname) != null
    const ariaCurrent = isActive ? (pathname === to ? 'page' : 'true') : undefined
    const accessibleName = scope ? t('nav.scopedLabel', { scope, label }) : label
    return (
        <Link
            to={to}
            className={`nav-link${isActive ? ' active' : ''}${className ? ` ${className}` : ''}`}
            title={collapsed ? accessibleName : undefined}
            aria-label={scope || collapsed ? accessibleName : undefined}
            aria-current={ariaCurrent}
        >
            <span className="nav-icon">{icon}</span>
            <span className="nav-label">{label}</span>
        </Link>
    )
}

export function Layout() {
    const { t } = useTranslation()
    const { user, logout, isImpersonating, impersonator, stopImpersonation } = useAuth()
    const { entries: providedEntries, managedZevs, selectedZevId, selectedZev, isSelectable, isLoading: managedZevLoading, setSelectedZevId } = useManagedZev()
    // A context without `entries` (the shape before #761) lists the readable ZEVs.
    const entries = providedEntries ?? managedZevs.map((zev) => ({
        id: zev.id,
        name: zev.name,
        relation: user?.role === 'admin' ? ('admin' as const) : ('manager' as const),
    }))
    const { shellRole, isZevScope, isParticipantScope } = useCommunityAccess()
    // Query the flag only for accounts with community-wide access.
    const feasibilityEnabledQuery = useQuery({
        queryKey: queryKeys.feasibility.enabled(),
        queryFn: fetchFeasibilityCalculatorEnabled,
        enabled: isZevScope,
        staleTime: 5 * 60 * 1000,
    })
    const location = useLocation()
    const navigate = useNavigate()
    const { pushToast } = useToast()
    const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
    const [isZevMenuOpen, setIsZevMenuOpen] = useState(false)
    const [isStoppingImpersonation, setIsStoppingImpersonation] = useState(false)
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
        if (typeof window === 'undefined') {
            return false
        }
        return window.localStorage.getItem('openzev.sidebarCollapsed') === 'true'
    })
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
    const isMobile = useMediaQuery(MOBILE_MEDIA_QUERY, undefined, { getInitialValueInEffect: false })
    const isNavigationCollapsed = isSidebarCollapsed && !isMobile
    const { dialog: zevSwitchDialog, confirm: confirmZevSwitch, handleConfirm: handleZevSwitchConfirm, handleCancel: handleZevSwitchCancel } = useConfirmDialog()
    const userMenuRef = useRef<HTMLDivElement | null>(null)
    const zevMenuRef = useRef<HTMLDivElement | null>(null)
    const userMenuTriggerRef = useRef<HTMLButtonElement | null>(null)
    const zevMenuTriggerRef = useRef<HTMLButtonElement | null>(null)
    const mobileMenuButtonRef = useRef<HTMLButtonElement | null>(null)
    const sidebarRef = useRef<HTMLElement | null>(null)
    const sidebarCollapseButtonRef = useRef<HTMLButtonElement | null>(null)
    const previousIsMobileRef = useRef(isMobile)
    const lastNavigationFocusRef = useRef<HTMLElement | null>(null)
    const mainRef = useRef<HTMLElement | null>(null)

    useRouteFocus(mainRef)

    useEffect(() => {
        window.localStorage.setItem('openzev.sidebarCollapsed', String(isSidebarCollapsed))
    }, [isSidebarCollapsed])

    useEffect(() => {
        setIsMobileMenuOpen(false)
    }, [location.pathname, isMobile])

    useLayoutEffect(() => {
        const focused = lastNavigationFocusRef.current
        // Forget unrelated unmounts; retain focus lost during a pending resize.
        if (focused && !focused.isConnected && window.matchMedia(MOBILE_MEDIA_QUERY).matches === previousIsMobileRef.current) {
            lastNavigationFocusRef.current = null
        }
    })

    useEffect(() => {
        if (previousIsMobileRef.current === isMobile) return
        previousIsMobileRef.current = isMobile
        // CSS can blur a hidden control before this effect runs.
        const focused = document.activeElement === document.body ? lastNavigationFocusRef.current : document.activeElement
        lastNavigationFocusRef.current = null
        const focusInSidebar = sidebarRef.current?.contains(focused)
        const focusInDropdown = focused instanceof Element && focused.closest('.zev-menu-dropdown') != null
        setIsZevMenuOpen(false)
        if (isMobile && focusInSidebar) {
            mobileMenuButtonRef.current?.focus()
        } else if (!isMobile && (focusInDropdown || focused === mobileMenuButtonRef.current)) {
            const focusTarget = zevMenuTriggerRef.current ?? sidebarCollapseButtonRef.current
            focusTarget?.focus()
        }
    }, [isMobile])

    // Prevent body scroll when mobile menu is open
    useEffect(() => {
        if (!isMobile || !isMobileMenuOpen) return
        const previous = document.body.style.overflow
        document.body.style.overflow = 'hidden'
        return () => { document.body.style.overflow = previous }
    }, [isMobile, isMobileMenuOpen])

    useEffect(() => {
        if (isUserMenuOpen) {
            userMenuRef.current?.querySelector<HTMLElement>('.user-menu-dropdown a, .user-menu-dropdown button')?.focus()
        }
    }, [isUserMenuOpen])

    useEffect(() => {
        if (isZevMenuOpen) {
            const dropdown = zevMenuRef.current?.querySelector<HTMLElement>('.zev-menu-dropdown')
            const firstOption = dropdown?.querySelector<HTMLElement>('button:not(:disabled)')
            const focusTarget = firstOption ?? dropdown
            focusTarget?.focus()
        }
    }, [isZevMenuOpen])

    useEffect(() => {
        function handleOutsideClick(event: MouseEvent) {
            if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
                setIsUserMenuOpen(false)
            }
            if (zevMenuRef.current && !zevMenuRef.current.contains(event.target as Node)) {
                setIsZevMenuOpen(false)
            }
        }

        function handleEscape(event: KeyboardEvent) {
            if (event.key === 'Escape') {
                if (isMobileMenuOpen) mobileMenuButtonRef.current?.focus()
                else if (isUserMenuOpen) userMenuTriggerRef.current?.focus()
                else if (isZevMenuOpen) zevMenuTriggerRef.current?.focus()
                setIsUserMenuOpen(false)
                setIsZevMenuOpen(false)
                setIsMobileMenuOpen(false)
            }
        }

        document.addEventListener('mousedown', handleOutsideClick)
        document.addEventListener('keydown', handleEscape)
        return () => {
            document.removeEventListener('mousedown', handleOutsideClick)
            document.removeEventListener('keydown', handleEscape)
        }
    }, [isUserMenuOpen, isZevMenuOpen, isMobileMenuOpen])

    const displayName = `${user?.first_name ?? ''} ${user?.last_name ?? ''}`.trim() || user?.username || ''
    // What the shell shows follows the account's relation to the selected
    // community, not a platform role (#761).
    const canManage = isZevScope
    const isFormerParticipant = shellRole === 'former'
    const selectedEntry = entries.find((entry) => entry.id === selectedZevId)
    const isGuest = shellRole === 'none'
    // Hub entries light on their sub-routes (chart/quality/imports are tabs
    // of the metering hub since phase 3).
    const meteringChartActive = useMatch('/metering/chart') != null
    const meteringQualityActive = useMatch('/metering/quality') != null
    const meteringImportsActive = useMatch('/metering/imports') != null
    const meteringActive = meteringChartActive || meteringQualityActive || meteringImportsActive
    const billingActive = useMatch('/billing/*') != null
    const adminOverviewMatch = useMatch('/admin/:tab')
    const adminOverviewActive = useMatch('/admin') != null ||
        ['overview', 'zevs', 'invoices', 'dynamic-sources', 'audit', 'health'].includes(adminOverviewMatch?.params.tab ?? '')

    // Whom the community's documents are from today (#761).
    const selectedZevIssuerName = selectedZev?.issuer?.display_name ?? ''

    // /admin/*: platform scope. Switcher inert; ZEV entry goes through Manage on /admin/zevs.
    const isPlatformScope = location.pathname.startsWith('/admin')

    // Close the ZEV menu when entering platform scope.
    useEffect(() => {
        if (isPlatformScope) {
            setIsZevMenuOpen(false)
        }
    }, [isPlatformScope])

    // A dirty settings draft lives in ZevSettingsPage; confirm before the
    // switcher drops it. Clean switches go through immediately.
    function requestZevSwitch(zevId: string) {
        if (zevId === selectedZevId) {
            return
        }
        if (!hasUnsavedZevSettingsDraft()) {
            setSelectedZevId(zevId)
            return
        }
        confirmZevSwitch({
            title: t('pages.zevSettings.unsavedGuardTitle'),
            message: t('pages.zevSettings.unsavedGuardSwitchMessage'),
            confirmText: t('pages.zevSettings.switchWithoutSaving'),
            onConfirm: () => {
                setSelectedZevId(zevId)
            },
        })
    }

    return (
        <div
            className={`shell${isNavigationCollapsed ? ' shell-collapsed' : ''}${isPlatformScope ? ' shell-scope-platform' : ''}`}
            onFocusCapture={(event) => {
                lastNavigationFocusRef.current = sidebarRef.current?.contains(event.target) || mobileMenuButtonRef.current?.contains(event.target)
                    ? event.target : null
            }}
            onBlurCapture={(event) => {
                // Retain lost focus only while a breakpoint change is pending.
                if (event.relatedTarget || window.matchMedia(MOBILE_MEDIA_QUERY).matches === previousIsMobileRef.current) {
                    lastNavigationFocusRef.current = null
                }
            }}
        >
            {/* Focus main without changing the URL hash; close an open drawer. */}
            <a
                className="skip-link"
                href="#main-content"
                onClick={(event) => {
                    event.preventDefault()
                    setIsMobileMenuOpen(false)
                    mainRef.current?.focus()
                }}
            >
                {t('nav.skipToContent')}
            </a>
            <div
                className={`sidebar-overlay${isMobileMenuOpen ? ' visible' : ''}`}
                onClick={() => setIsMobileMenuOpen(false)}
            />
            <aside ref={sidebarRef} id="app-sidebar" className={`sidebar${isNavigationCollapsed ? ' collapsed' : ''}${isMobileMenuOpen ? ' mobile-open' : ''}`}>
                {/* Persistent scope context (replaces switcher on platform routes). */}
                <div className="sidebar-fixed">
                    <div className="sidebar-brand-row">
                        {/* Horizontal lockup of the logo; the wordmark names the app. */}
                        <div className="sidebar-brand">
                            <img src="/brand/openzev-mark.png" alt="" className="sidebar-brand-mark" />
                            <img
                                src="/brand/openzev-wordmark-dark.png"
                                alt={t('app.title')}
                                className="sidebar-brand-wordmark"
                            />
                        </div>
                        <button
                            ref={sidebarCollapseButtonRef}
                            type="button"
                            className="sidebar-collapse-button"
                            onClick={() => setIsSidebarCollapsed((prev) => !prev)}
                            aria-label={isSidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
                            title={isSidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
                        >
                            <ChevronIcon direction={isSidebarCollapsed ? 'right' : 'left'} />
                        </button>
                    </div>

                    {/* Platform scope swaps the switcher for an explicit indicator. */}
                    {canManage && isPlatformScope && (
                        <div className="sidebar-scope-chip" title={t('nav.platformScope')}>
                            <span className="nav-icon" aria-hidden="true"><PlatformIcon /></span>
                            <span className="sidebar-scope-chip-label">{t('nav.platformScope')}</span>
                        </div>
                    )}

                    {/* Exactly one managed community means there is nothing to
                        switch — the page eyebrows carry the name instead. */}
                    {(canManage || entries.length > 1) && !isPlatformScope && entries.length !== 1 && (
                        <div
                            className="user-menu zev-menu sidebar-zev-menu"
                            ref={zevMenuRef}
                            onBlur={(event) => {
                                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setIsZevMenuOpen(false)
                            }}
                        >
                            <button
                                ref={zevMenuTriggerRef}
                                type="button"
                                className="user-menu-trigger"
                                aria-label={selectedZev?.name ? t('nav.manageZevFor', { name: selectedZev.name }) : t('nav.manageZev')}
                                aria-expanded={isZevMenuOpen}
                                aria-controls="zev-menu-list"
                                onClick={() => {
                                    setIsUserMenuOpen(false)
                                    // Auto-expand sidebar if collapsed before opening menu.
                                    if (isNavigationCollapsed) {
                                        setIsSidebarCollapsed(false)
                                        setIsZevMenuOpen(true)
                                    } else {
                                        setIsZevMenuOpen((prev) => !prev)
                                    }
                                }}
                            >
                                <span className="user-avatar" aria-hidden="true">
                                    {selectedEntry?.name ? initialsOf(selectedEntry.name) : <PlatformIcon />}
                                </span>
                                <span className="user-meta">
                                    <strong>{selectedEntry?.name || selectedZev?.name || t('nav.noZevSelected')}</strong>
                                    <small>
                                        {/* The issuer when the community has one; otherwise
                                            how this account relates to the community. */}
                                        {selectedZevIssuerName
                                            || (selectedEntry ? t(`nav.relation.${selectedEntry.relation}`) : '-')}
                                    </small>
                                </span>
                            </button>

                            {isZevMenuOpen && (
                                <div className="user-menu-dropdown zev-menu-dropdown" id="zev-menu-list" role="group" aria-label={t('nav.manageZev')} tabIndex={-1}>
                                    <div className="user-menu-section">
                                        <div className="user-menu-section-title">{t('nav.manageZev')}</div>
                                        <div className="zev-dropdown-list">
                                            {managedZevLoading ? (
                                                <div className="zev-dropdown-item zev-dropdown-item-muted">{t('nav.loadingZevs')}</div>
                                            ) : entries.length === 0 ? (
                                                <div className="zev-dropdown-item zev-dropdown-item-muted">{t('nav.noZevAvailable')}</div>
                                            ) : (
                                                entries.map((zev) => {
                                                    const isSelected = zev.id === selectedZevId
                                                    return (
                                                        <button
                                                            key={zev.id}
                                                            type="button"
                                                            className={`zev-dropdown-item${isSelected ? ' active' : ''}`}
                                                            onClick={() => {
                                                                zevMenuTriggerRef.current?.focus()
                                                                if (isSelectable) {
                                                                    requestZevSwitch(zev.id)
                                                                }
                                                                setIsZevMenuOpen(false)
                                                            }}
                                                            disabled={!isSelectable && !isSelected}
                                                            aria-current={isSelected ? 'true' : undefined}
                                                        >
                                                            <span>{zev.name}</span>
                                                            {zev.relation !== 'admin' && (
                                                                <small className="zev-dropdown-relation">{t(`nav.relation.${zev.relation}`)}</small>
                                                            )}
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
                </div>

                <div className="sidebar-top">
                    <nav className="nav-list">
                        {canManage && (
                            <>
                                <SidebarLink to="/" label={t('nav.overview')} icon={<DashboardIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/dashboard" label={t('nav.energyBalance')} icon={<EnergyIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/metering/chart" label={t('nav.metering')} icon={<ChartIcon />} active={meteringActive} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/billing/invoices" label={t('nav.billing')} icon={<InvoiceIcon />} active={billingActive} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/reports" label={t('nav.reports')} icon={<ReportsIcon />} collapsed={isNavigationCollapsed} />
                            </>
                        )}

                        {isGuest && (
                            <SidebarLink to="/account" label={t('account.title')} icon={<AccountIcon />} className="nav-standalone" collapsed={isNavigationCollapsed} />
                        )}

                        {isParticipantScope && !isFormerParticipant && (
                            <>
                                <SidebarLink to="/" label={t('nav.dashboard')} icon={<DashboardIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/me/invoices" label={t('nav.myInvoices')} icon={<InvoiceIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/me/statement" label={t('nav.annualStatement')} icon={<ReportsIcon />} collapsed={isNavigationCollapsed} />
                            </>
                        )}

                        {/* A former participant keeps only the invoices it was sent. */}
                        {isFormerParticipant && (
                            <SidebarLink to="/me/invoices" label={t('nav.myInvoices')} icon={<InvoiceIcon />} collapsed={isNavigationCollapsed} />
                        )}

                        {canManage && (
                            <div className="nav-section nav-section-start" role="group" aria-label={t('nav.setupGroup')}>
                                <div className="nav-group-label" aria-hidden="true">{t('nav.setupGroup')}</div>
                                <SidebarLink to="/participants" label={t('nav.participants')} icon={<UsersIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/metering/points" label={t('nav.meteringPoints')} icon={<PlugIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/tariffs" label={t('nav.tariffs')} icon={<TagIcon />} collapsed={isNavigationCollapsed} />
                                <SidebarLink to="/zev-settings" label={t('nav.zevSettings')} icon={<SettingsIcon />} collapsed={isNavigationCollapsed} />
                            </div>
                        )}

                        {canManage && feasibilityEnabledQuery.data === true && (
                            <SidebarLink to="/feasibility" label={t('nav.feasibility')} icon={<CalculatorIcon />} className="nav-standalone" collapsed={isNavigationCollapsed} />
                        )}

                        {user?.role === 'admin' && (
                            <div className="nav-section nav-section-end" role="group" aria-label={t('nav.platformGroup')}>
                                <div className="nav-group-label nav-group-label-platform" aria-hidden="true">{t('nav.platformGroup')}</div>
                                <SidebarLink
                                    to="/admin" end active={adminOverviewActive}
                                    label={t('nav.adminOverview')} scope={t('nav.platformGroup')}
                                    icon={<OverviewIcon />} collapsed={isNavigationCollapsed}
                                />
                                <SidebarLink
                                    to="/admin/accounts" label={t('nav.adminAccounts')} scope={t('nav.platformGroup')}
                                    icon={<AccountsIcon />} collapsed={isNavigationCollapsed}
                                />
                                <SidebarLink
                                    to="/admin/templates" label={t('nav.adminTemplates')} scope={t('nav.platformGroup')}
                                    icon={<PdfIcon />} collapsed={isNavigationCollapsed}
                                />
                                <SidebarLink
                                    to="/admin/system-settings" label={t('nav.adminSystemSettings')} scope={t('nav.platformGroup')}
                                    icon={<SystemIcon />} collapsed={isNavigationCollapsed}
                                />
                            </div>
                        )}
                    </nav>
                </div>
                <div className="sidebar-footer">
                    <div
                        className="user-menu sidebar-user"
                        ref={userMenuRef}
                        onBlur={(event) => {
                            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setIsUserMenuOpen(false)
                        }}
                    >
                        <button
                            ref={userMenuTriggerRef}
                            type="button"
                            className="user-menu-trigger"
                            aria-expanded={isUserMenuOpen}
                            aria-controls="user-menu-list"
                            // Collapsed, the name is hidden: the label names the button, the title shows it.
                            aria-label={isNavigationCollapsed ? displayName : undefined}
                            title={isNavigationCollapsed ? displayName : undefined}
                            onClick={() => {
                                setIsZevMenuOpen(false)
                                // The panel needs the full width: expand a collapsed sidebar first.
                                if (isNavigationCollapsed) {
                                    setIsSidebarCollapsed(false)
                                    setIsUserMenuOpen(true)
                                } else {
                                    setIsUserMenuOpen((prev) => !prev)
                                }
                            }}
                        >
                            <span className="user-avatar" aria-hidden="true">{initialsOf(displayName)}</span>
                            <span className="user-meta">
                                <strong>{displayName}</strong>
                                <small>{user?.email}</small>
                            </span>
                            <span className="user-menu-caret" aria-hidden="true"><SelectorIcon /></span>
                        </button>
                        {isUserMenuOpen && (
                            <div className="user-menu-dropdown" id="user-menu-list">
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
                    <a
                        className="sidebar-github-link"
                        href="https://github.com/splattner/openzev"
                        target="_blank"
                        rel="noopener noreferrer"
                        title={t('nav.sourceCode')}
                    >
                        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.01.08-2.11 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.91.08 2.11.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
                        </svg>
                        <span className="sidebar-github-label">OpenZEV <span className="sidebar-github-version">v{(pkg as any).version ?? 'dev'}</span></span>
                    </a>
                </div>
            </aside>

            <div className="content">
                <header className="top-nav">
                    <div className="mobile-bar">
                        <button
                            ref={mobileMenuButtonRef}
                            type="button"
                            className="mobile-menu-button"
                            onClick={() => setIsMobileMenuOpen((prev) => !prev)}
                            aria-label={t('nav.menu')}
                            aria-expanded={isMobileMenuOpen}
                            aria-controls="app-sidebar"
                        >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <path d="M3 12h18M3 6h18M3 18h18" />
                            </svg>
                        </button>
                        <span className="mobile-bar-brand" aria-hidden="true">
                            <img src="/brand/openzev-mark.png" alt="" />
                            <img src="/brand/openzev-wordmark-dark.png" alt="" />
                        </span>
                    </div>

                    {isImpersonating && impersonator && (
                        <div className="impersonation-banner" role="status">
                            <span>
                                {t('nav.impersonatingAs', { name: displayName || user?.username })}
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
                                    } catch (error) {
                                        const message = apiErrorPayload(error)?.code === 'impersonation_session_expired'
                                            ? 'auth.adminSessionExpired'
                                            : 'common.error'
                                        pushToast(t(message), 'error')
                                    } finally {
                                        setIsStoppingImpersonation(false)
                                    }
                                }}
                            >
                                {t('nav.stopImpersonation')}
                            </button>
                        </div>
                    )}
                </header>
                <main id="main-content" ref={mainRef} className="content-main" tabIndex={-1}>
                    <Outlet />
                </main>
            </div>
            {zevSwitchDialog && (
                <ConfirmDialog
                    {...zevSwitchDialog}
                    onConfirm={handleZevSwitchConfirm}
                    onCancel={handleZevSwitchCancel}
                />
            )}
        </div>
    )
}

function DashboardIcon() {
    return <IconSvg path="M3 12.75 12 4l9 8.75V21a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
}

function UsersIcon() {
    return <IconSvg path="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2m18 0v-2a4 4 0 0 0-3-3.87M14 4.13a4 4 0 0 1 0 7.75M9.5 11A4 4 0 1 0 9.5 3a4 4 0 0 0 0 8Z" />
}


/** ID card distinguishes accounts from community participants. */
function AccountsIcon() {
    return (
        <IconSvg
            path={
                <>
                    <rect x="2.5" y="5" width="19" height="14" rx="2" />
                    <circle cx="8.5" cy="11" r="2" />
                    <path d="M5.6 16c.6-1.3 1.7-2 2.9-2s2.3.7 2.9 2M14.5 10h4M14.5 13.5h3" />
                </>
            }
        />
    )
}

/** Host stack distinguishes platform settings from community settings. */
function SystemIcon() {
    return (
        <IconSvg
            path={
                <>
                    <rect x="3" y="4" width="18" height="6.5" rx="2" />
                    <rect x="3" y="13.5" width="18" height="6.5" rx="2" />
                    <path d="M7 7.25h.01M7 16.75h.01M11 7.25h4M11 16.75h4" />
                </>
            }
        />
    )
}

function PlugIcon() {
    return <IconSvg path="M9 7V3m6 4V3m-7 8h8a2 2 0 0 0 2-2V7H6v2a2 2 0 0 0 2 2Zm4 0v6a4 4 0 0 1-4 4h-1" />
}

function ChartIcon() {
    return <IconSvg path="M4 19V5m0 14h16M8 17v-5m4 5V8m4 9V11" />
}

function EnergyIcon() {
    return <IconSvg path="m13 2-9 12h7l-1 8 10-13h-7z" />
}

function TagIcon() {
    return <IconSvg path="m20.59 13.41-7.18 7.18a2 2 0 0 1-2.83 0L3 13V3h10l7.59 7.59a2 2 0 0 1 0 2.82ZM7.5 7.5h.01" />
}

function InvoiceIcon() {
    return <IconSvg path="M7 3h8l4 4v14l-2-1-2 1-2-1-2 1-2-1-2 1V4a1 1 0 0 1 1-1Zm1 6h8m-8 4h8m-8 4h5" />
}

function CalculatorIcon() {
    return (
        <IconSvg
            path={
                <>
                    <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
                    <line x1="8" y1="6" x2="16" y2="6" />
                    <path d="M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" />
                </>
            }
        />
    )
}


function SettingsIcon() {
    return <IconSvg path="M12 8.5A3.5 3.5 0 1 1 8.5 12 3.5 3.5 0 0 1 12 8.5Zm7 3.5.94-.54-1-1.73-1.07.18a6.97 6.97 0 0 0-1.2-1.2l.18-1.07-1.73-1-.54.94a6.97 6.97 0 0 0-1.55-.42L12.5 4h-2l-.53 1.16a6.97 6.97 0 0 0-1.55.42l-.54-.94-1.73 1 .18 1.07a6.97 6.97 0 0 0-1.2 1.2l-1.07-.18-1 1.73.94.54a6.97 6.97 0 0 0 0 1.84l-.94.54 1 1.73 1.07-.18c.33.45.74.86 1.2 1.2l-.18 1.07 1.73 1 .54-.94c.49.2 1.01.34 1.55.42L10.5 20h2l.53-1.16c.54-.08 1.06-.22 1.55-.42l.54.94 1.73-1-.18-1.07c.45-.33.86-.74 1.2-1.2l1.07.18 1-1.73-.94-.54a6.97 6.97 0 0 0 0-1.84Z" />
}

function OverviewIcon() {
    return <IconSvg path="M4 4h7v7H4zm9 0h7v4h-7zM4 13h4v7H4zm6 3h10v4H10z" />
}

function PlatformIcon() {
    return <IconSvg path="M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01" />
}

function PdfIcon() {
    return <IconSvg path="M7 3h8l4 4v14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm1 14h2.5a2.5 2.5 0 0 0 0-5H8Zm1.5-3.5h1a1 1 0 1 1 0 2h-1Zm5.5-1.5h-3v5h1.5v-1.75h1.25M13.5 13.5h1.5m-1.5 2h1.25" />
}


function ReportsIcon() {
    return <IconSvg path="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM14 2v6h6M8 13h8M8 17h8M8 9h3" />
}

function AccountIcon() {
    return <IconSvg path="M20 21a8 8 0 0 0-16 0m8-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
}

function LogoutIcon() {
    return <IconSvg path="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9" />
}

function SelectorIcon() {
    return <IconSvg path="m7 15 5 5 5-5M7 9l5-5 5 5" />
}

function ChevronIcon({ direction }: { direction: 'left' | 'right' }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {direction === 'left' ? <path d="m15 18-6-6 6-6" /> : <path d="m9 18 6-6-6-6" />}
        </svg>
    )
}

/** Up to two word initials, skipping symbols. Empty input renders '·'. */
function initialsOf(name: string | undefined | null): string {
    const initials = (name ?? '').normalize('NFC').split(/\s+/)
        .flatMap((word) => word.match(/[\p{L}\p{N}]/u)?.[0] ?? [])
        .slice(0, 2)
        .map((letter) => Array.from(letter.toUpperCase())[0]).join('')
    return initials || '·'
}

function IconSvg({ path }: { path: string | ReactNode }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {typeof path === 'string' ? <path d={path} /> : path}
        </svg>
    )
}
