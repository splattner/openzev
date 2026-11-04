import type { Notification, PaginatedResponse } from '../../types/api'
import { api } from './client'

export async function fetchNotifications(params: { unread?: boolean; zev?: string; page?: number } = {}): Promise<PaginatedResponse<Notification>> {
    const { data } = await api.get<PaginatedResponse<Notification>>('/notifications/', {
        params: { ...(params.unread ? { unread: 'true' } : {}), ...(params.zev ? { zev: params.zev } : {}), ...(params.page ? { page: params.page } : {}) },
    })
    return data
}

export async function fetchUnreadNotificationCount(): Promise<number> {
    const { data } = await api.get<{ count: number }>('/notifications/unread-count/')
    return data.count
}

export async function markNotificationRead(id: string): Promise<Notification> {
    const { data } = await api.post<Notification>(`/notifications/${id}/read/`)
    return data
}

export async function markAllNotificationsRead(zevId?: string): Promise<number> {
    const { data } = await api.post<{ updated: number }>('/notifications/read-all/', undefined, {
        params: zevId ? { zev: zevId } : undefined,
    })
    return data.updated
}
