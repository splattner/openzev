import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PdfPreview } from '../src/components/PdfPreview'
import { deferred, flush, pdfBlob } from './pdf-test-utils'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root: Root
let container: HTMLDivElement

function renderPreview(props: Parameters<typeof PdfPreview>[0]) {
  act(() => {
    root.render(createElement(PdfPreview, props))
  })
}

describe('PdfPreview', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:new-tab-1')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps the footer link layout without actions', async () => {
    renderPreview({ src: 'blob:preview-1' })
    await flush()

    const frame = container.querySelector('.pdf-frame')
    expect(frame?.querySelector('.pdf-preview-actions')).toBeNull()
    const footer = frame?.querySelector('p.muted')
    expect(footer).toBeTruthy()
    const links = frame ? frame.querySelectorAll('a') : []
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('blob:preview-1')
    const iframe = frame ? frame.querySelector('iframe') : null
    expect(iframe).toBeTruthy()
    expect(footer!.compareDocumentPosition(iframe!))
      .toBe(Node.DOCUMENT_POSITION_PRECEDING)
  })

  it('renders supplied actions and the single new-tab link above the iframe', async () => {
    const fetcher = vi.fn().mockResolvedValue(pdfBlob())
    renderPreview({
      src: 'blob:preview-1',
      actions: createElement('button', { type: 'button' }, 'pdf.download'),
      openInNewTabFetcher: fetcher,
    })
    await flush()

    const frame = container.querySelector('.pdf-frame')!
    const actionsRow = frame.querySelector('.pdf-preview-actions')!
    expect(actionsRow).toBeTruthy()
    expect(actionsRow.textContent).toContain('pdf.download')
    expect(actionsRow.textContent).toContain('pdf.openInNewTab')
    expect(frame.querySelectorAll('a')).toHaveLength(1)
    expect(frame.querySelector('p.muted')).toBeNull()
    expect(actionsRow.compareDocumentPosition(frame.querySelector('iframe')!))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('opens an independent object URL for a new tab and revokes it later', async () => {
    const blob = pdfBlob()
    const pending = deferred<Blob>()
    const fetcher = vi.fn(() => pending.promise)
    const popup = { opener: window, location: { replace: vi.fn() } }
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    renderPreview({ src: 'blob:preview-1', openInNewTabFetcher: fetcher })

    const link = container.querySelector('.pdf-frame a') as HTMLAnchorElement
    vi.useFakeTimers()
    try {
      await act(async () => {
        link.click()
      })

      expect(openSpy).toHaveBeenCalledWith('', '_blank')
      expect(popup.opener).toBeNull()
      expect(fetcher).toHaveBeenCalledOnce()
      expect(popup.location.replace).not.toHaveBeenCalled()

      await act(async () => {
        pending.resolve(blob)
        await pending.promise
      })

      expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
      expect(popup.location.replace).toHaveBeenCalledWith('blob:new-tab-1')
      expect(URL.revokeObjectURL).not.toHaveBeenCalled()

      await act(async () => {
        vi.advanceTimersByTime(60000)
      })
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:new-tab-1')
    } finally {
      vi.useRealTimers()
    }
  })

  it('falls back to the source URL when the new-tab fetch fails', async () => {
    const popup = { opener: window, location: { replace: vi.fn() } }
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const fetcher = vi.fn().mockRejectedValue(new Error('fetch failed'))
    renderPreview({ src: 'blob:preview-1', openInNewTabFetcher: fetcher })
    await flush()

    const link = container.querySelector('.pdf-frame a') as HTMLAnchorElement
    await act(async () => {
      link.click()
    })
    await flush()

    expect(openSpy).toHaveBeenCalledWith('', '_blank')
    expect(popup.location.replace).toHaveBeenCalledWith('blob:preview-1')
  })

  it('links straight to the source URL without a fetcher', async () => {
    renderPreview({ src: 'blob:preview-1' })
    await flush()

    const link = container.querySelector('.pdf-frame a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('blob:preview-1')
    expect(link.getAttribute('target')).toBe('_blank')
  })
})
