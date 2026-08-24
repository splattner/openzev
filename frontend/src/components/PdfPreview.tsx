import { useTranslation } from 'react-i18next'

interface PdfPreviewProps {
  /** Object URL — callers own the authenticated blob fetch that creates it. */
  src: string | null
  title?: string
  height?: string
}

/**
 * Embeds a real PDF (object URL) in an iframe inside a paper-style frame.
 *
 * The caller owns fetch + revoke: create the URL with `URL.createObjectURL(blob)`
 * and revoke it on unmount. All document embeds must blob-fetch — an iframe
 * `src` cannot attach an `Authorization` header, and attachment-disposition
 * endpoints would download instead of rendering.
 */
export function PdfPreview({ src, title, height = '72vh' }: PdfPreviewProps) {
  const { t } = useTranslation()

  return (
    <div className="pdf-frame">
      {src ? (
        <>
          <iframe
            src={src}
            title={title ?? t('pdf.previewTitle')}
            style={{ width: '100%', height, border: 0, display: 'block' }}
          />
          <p className="muted" style={{ padding: '0.5rem 0.75rem', margin: 0 }}>
            <a href={src} target="_blank" rel="noreferrer">
              {t('pdf.openInNewTab')}
            </a>
          </p>
        </>
      ) : (
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          <p className="muted" style={{ margin: 0 }}>{t('pdf.noDocument')}</p>
        </div>
      )}
    </div>
  )
}
