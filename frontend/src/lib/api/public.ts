import type { PublicInvoice } from '../../types/api'
import { api, API_BASE_URL } from './client'

/**
 * Fetch one invoice by the credential printed on it.
 *
 * Every failure is a 404 by design — unknown link, revoked link, wrong secret,
 * ZEV not opted in — so callers get one "not valid" state rather than a
 * taxonomy that would tell a scanner which links exist. It also means this
 * never returns 401, so the shared client's token-refresh interceptor stays
 * out of the way on a page with no session.
 */
export async function fetchPublicInvoice(prefix: string, secret: string): Promise<PublicInvoice> {
    const { data } = await api.get<PublicInvoice>(`/public/invoices/${prefix}/`, {
        params: { s: secret },
    })
    return data
}

/** The PDF for that invoice. A plain URL: the browser fetches it directly. */
export function publicInvoicePdfUrl(prefix: string, secret: string): string {
    return `${API_BASE_URL}/public/invoices/${prefix}/pdf/?s=${encodeURIComponent(secret)}`
}

/**
 * Ask for a sign-in link, identified by the invoice link itself.
 *
 * There is deliberately no email parameter: the destination comes from the
 * participant record, never from the caller. That is what makes account
 * enumeration impossible here rather than merely hard — and it is why the
 * response is always 202, whatever the outcome.
 */
export async function requestMagicLink(prefix: string, secret: string): Promise<void> {
    await api.post('/public/magic-link/request/', { prefix, s: secret })
}

/** Trade a one-time link for a session. Throws on an expired or used link. */
export async function consumeMagicLink(token: string): Promise<void> {
    await api.post('/public/magic-link/consume/', { token })
}

export interface PublicInvoiceChart {
    key: 'energy' | 'hourly' | 'flow'
    title: string
    description: string
    svg: string
}

/**
 * The invoice's insights page, as data.
 *
 * Headings come from the server rather than the SPA's own locale: the SVGs
 * embed their labels in the ZEV's invoice language, and a German diagram under
 * an English heading reads as a bug. The document has one language.
 *
 * Charts that cannot be drawn are absent rather than null — a fee-only invoice
 * has no consumption to profile.
 */
export interface PublicInvoiceCharts {
    title: string
    intro: string
    charts: PublicInvoiceChart[]
}

/**
 * Fetch the charts, separately from the invoice.
 *
 * Their own request because building them costs a full period of allocation
 * work on the server: the invoice figures should not wait behind a picture.
 */
export async function fetchPublicInvoiceCharts(
    prefix: string,
    secret: string,
): Promise<PublicInvoiceCharts> {
    const { data } = await api.get<PublicInvoiceCharts>(
        `/public/invoices/${prefix}/charts/`,
        { params: { s: secret } },
    )
    return data
}
