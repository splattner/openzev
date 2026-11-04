import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
    fetchNotifications,
    fetchUnreadNotificationCount,
    markAllNotificationsRead,
    markNotificationRead,
} from '../lib/api/notifications'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useOptionalAppSettings } from '../lib/appSettings'
import { notificationLink, notificationText } from '../lib/notifications'
import type { Notification } from '../types/api'
import { IconSvg } from './IconSvg'

const POLL_INTERVAL_MS = 60_000
const BADGE_CAP = 99

function BellIcon() {
    return <IconSvg path="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9m4.3 13a1.94 1.94 0 0 0 3.4 0" />
}

/** The shell's bell: an unread count, and a panel of recent notifications that lead to what they are about. */
export function NotificationBell() {
    const { t } = useTranslation()
    const settings = useOptionalAppSettings() ?? undefined
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [open, setOpen] = useState(false)
    const rootRef = useRef<HTMLDivElement | null>(null)
    const triggerRef = useRef<HTMLButtonElement | null>(null)
    const panelId = useId()

    // Polled while the tab is visible (no websockets in this version).
    const countQuery = useQuery({
        queryKey: queryKeys.notifications.unreadCount(),
        queryFn: fetchUnreadNotificationCount,
        refetchInterval: POLL_INTERVAL_MS,
        refetchIntervalInBackground: false,
    })
    const listQuery = useQuery({
        queryKey: queryKeys.notifications.list(),
        queryFn: () => fetchNotifications(),
        enabled: open,
    })

    const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all })
    const readOne = useMutation({ mutationFn: markNotificationRead, onSuccess: invalidate })
    const readAll = useMutation({ mutationFn: () => markAllNotificationsRead(), onSuccess: invalidate })

    useEffect(() => {
        if (!open) return
        function onPointerDown(event: MouseEvent) {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
        }
        function onKeyDown(event: KeyboardEvent) {
            if (event.key === 'Escape') {
                setOpen(false)
                triggerRef.current?.focus()
            }
        }
        document.addEventListener('mousedown', onPointerDown)
        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('mousedown', onPointerDown)
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [open])

    const unread = countQuery.data ?? 0
    const items = listQuery.data?.results ?? []
    // A community name only helps an account that sees more than one.
    const showCommunity = new Set(items.map((item) => item.zev)).size > 1

    function openNotification(notification: Notification) {
        if (notification.read_at === null) readOne.mutate(notification.id)
        setOpen(false)
        const link = notificationLink(notification)
        if (link) navigate(link)
    }

    return (
        <div className="notification-bell" ref={rootRef}>
            <button
                ref={triggerRef}
                type="button"
                className="notification-bell-trigger"
                aria-expanded={open}
                aria-controls={panelId}
                aria-label={unread > 0 ? t('notifications.triggerUnread', { count: unread }) : t('notifications.trigger')}
                onClick={() => setOpen((previous) => !previous)}
            >
                <BellIcon />
                {unread > 0 && (
                    <span className="notification-bell-badge" aria-hidden="true">
                        {unread > BADGE_CAP ? `${BADGE_CAP}+` : unread}
                    </span>
                )}
            </button>
            {open && (
                <div className="notification-panel" id={panelId} role="dialog" aria-label={t('notifications.title')}>
                    <div className="notification-panel-header">
                        <strong>{t('notifications.title')}</strong>
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            disabled={unread === 0 || readAll.isPending}
                            onClick={() => readAll.mutate()}
                        >
                            {t('notifications.markAllRead')}
                        </button>
                    </div>
                    {listQuery.isError ? (
                        <p className="notification-panel-empty" role="alert">{t('notifications.loadError')}</p>
                    ) : listQuery.isPending ? (
                        <p className="notification-panel-empty" role="status">{t('common.loading')}</p>
                    ) : items.length === 0 ? (
                        <p className="notification-panel-empty">{t('notifications.empty')}</p>
                    ) : (
                        <ul className="notification-list">
                            {items.map((notification) => (
                                <li key={notification.id}>
                                    <button
                                        type="button"
                                        className={`notification-item${notification.read_at === null ? ' is-unread' : ''}`}
                                        onClick={() => openNotification(notification)}
                                    >
                                        <span className="notification-item-text">
                                            {notification.read_at === null && (
                                                <span className="visually-hidden">{t('notifications.unreadMarker')} </span>
                                            )}
                                            {notificationText(t, notification)}
                                        </span>
                                        <span className="notification-item-meta">
                                            {showCommunity && <span>{notification.zev_name} · </span>}
                                            {formatDateTime(notification.created_at, settings)}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    )
}
