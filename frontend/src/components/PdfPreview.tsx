import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

interface PdfPreviewProps {
  /** Object URL — callers own the authenticated blob fetch that creates it. */
  src: string | null
  title?: string
  height?: string
  /** Blob for an independent new tab. Without it, the link uses `src`. */
  openInNewTabFetcher?: () => Promise<Blob>
  actions?: ReactNode
}

/** Displays a caller-owned PDF object URL; the caller revokes it. */
export function PdfPreview({ src, title, height = '72vh', openInNewTabFetcher, actions }: PdfPreviewProps) {
  const { t } = useTranslation()

  const openIndependentTab = async (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (!openInNewTabFetcher || !src) return

    // Open before awaiting the fetch to retain the click's popup permission.
    const newTab = window.open('', '_blank')
    if (!newTab) return
    event.preventDefault()
    newTab.opener = null

    try {
      const blob = await openInNewTabFetcher()
      const url = URL.createObjectURL(blob)
      newTab.location.replace(url)
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch {
      newTab.location.replace(src)
    }
  }

  const newTabLink = (
    <a href={src ?? undefined} target="_blank" rel="noreferrer" onClick={openIndependentTab}>
      {t('pdf.openInNewTab')}
    </a>
  )

  return (
    <div className="pdf-frame">
      {src ? (
        <>
          {actions ? (
            <div className="actions-row actions-row-wrap pdf-preview-actions">
              {actions}
              {newTabLink}
            </div>
          ) : null}
          <iframe
            src={src}
            title={title ?? t('pdf.previewTitle')}
            style={{ width: '100%', height, border: 0, display: 'block' }}
          />
          {actions ? null : (
            <p className="muted" style={{ padding: '0.5rem 0.75rem', margin: 0 }}>
              {newTabLink}
            </p>
          )}
        </>
      ) : (
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          <p className="muted" style={{ margin: 0 }}>{t('pdf.noDocument')}</p>
        </div>
      )}
    </div>
  )
}
