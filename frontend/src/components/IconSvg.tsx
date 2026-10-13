import type { ReactNode } from 'react'

/** The sidebar's outline icon style: a 24px stroke drawing in the text colour. */
export function IconSvg({ path }: { path: string | ReactNode }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {typeof path === 'string' ? <path d={path} /> : path}
        </svg>
    )
}

/** Metering points, in the sidebar and wherever a list marks them. */
export function PlugIcon() {
    return <IconSvg path="M9 7V3m6 4V3m-7 8h8a2 2 0 0 0 2-2V7H6v2a2 2 0 0 0 2 2Zm4 0v6a4 4 0 0 1-4 4h-1" />
}
