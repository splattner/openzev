import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { deferred, pdfBlob } from './pdf-test-utils'

const api = vi.hoisted(() => {
    const current = { template_name: 'invoice', content: 'Default PDF', is_customized: false, is_stale: false }
    return {
        current,
        fetch: vi.fn(async () => ({ ...current, fields: [] })),
        save: vi.fn(async (content: string) => {
            Object.assign(current, { content, is_customized: true })
            return { ...current, detail: 'saved' }
        }),
        reset: vi.fn(async () => {
            Object.assign(current, { content: 'Default PDF', is_customized: false })
            return { ...current, detail: 'reset' }
        }),
        preview: vi.fn(() => new Promise<Blob>(() => {})),
    }
})
const toastSpy = vi.hoisted(() => vi.fn())

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: toastSpy }) }))
vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoicePdfTemplate: api.fetch,
    updateInvoicePdfTemplate: api.save,
    resetInvoicePdfTemplate: api.reset,
    fetchContractPdfTemplate: api.fetch,
    updateContractPdfTemplate: api.save,
    resetContractPdfTemplate: api.reset,
    fetchAnnualStatementPdfTemplate: api.fetch,
    updateAnnualStatementPdfTemplate: api.save,
    resetAnnualStatementPdfTemplate: api.reset,
    fetchCreditNotePdfTemplate: api.fetch,
    updateCreditNotePdfTemplate: api.save,
    resetCreditNotePdfTemplate: api.reset,
    previewPdfTemplateBlob: api.preview,
}))
vi.mock('../src/components/PdfPreview', () => ({
    PdfPreview: ({ src }: { src: string | null }) => createElement('output', { 'data-preview-src': src }),
}))

import { AdminPdfTemplatesPage } from '../src/pages/AdminPdfTemplatesPage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const cleanups: (() => void)[] = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    Object.assign(api.current, { content: 'Default PDF', is_customized: false, is_stale: false })
    api.fetch.mockClear()
    api.save.mockClear()
    api.reset.mockClear()
    api.preview.mockReset()
    toastSpy.mockClear()
    vi.useRealTimers()
    vi.restoreAllMocks()
})

async function renderEditor() {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    await act(async () => root.render(createElement(MantineProvider, null,
        createElement(QueryClientProvider, { client },
            createElement(AdminPdfTemplatesPage, { embedded: true, template: 'invoice' }),
        ),
    )))
    await vi.waitFor(() => expect(container.querySelector('.template-source')).not.toBeNull())
    await act(async () => {
        Array.from(container.querySelectorAll('button'))
            .find((button) => button.textContent === 'admin.backToEditor')!.click()
    })
    cleanups.push(() => { act(() => root.unmount()); container.remove(); client.clear() })
    return { container, client, editor: container.querySelector<HTMLTextAreaElement>('textarea.template-editor')! }
}

function edit(editor: HTMLTextAreaElement, value: string) {
    act(() => {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(editor, value)
        editor.dispatchEvent(new Event('input', { bubbles: true }))
    })
}

function click(container: ParentNode, label: string) {
    const button = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
        .find((candidate) => candidate.textContent === label)!
    button.click()
}

describe('platform PDF template source', () => {
    it.each(['success', 'error'])('keeps the newer preview %s when an older error finishes parsing', async (outcome) => {
        const { container } = await renderEditor()
        vi.useFakeTimers()
        vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:new-preview')
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
        const oldErrorText = deferred<string>()
        const oldErrorBody = new Blob()
        oldErrorBody.text = vi.fn(() => oldErrorText.promise)
        const newerPreview = deferred<Blob>()
        api.preview.mockRejectedValueOnce({ response: { status: 400, data: oldErrorBody } })
            .mockReturnValueOnce(newerPreview.promise)

        await act(async () => { click(container, 'admin.preview') })
        await act(async () => { await vi.advanceTimersByTimeAsync(700) })
        expect(oldErrorBody.text).toHaveBeenCalledOnce()
        await act(async () => { click(container, 'admin.previewRenderNow') })
        expect(api.preview).toHaveBeenCalledTimes(2)
        await act(async () => {
            if (outcome === 'success') newerPreview.resolve(pdfBlob())
            else newerPreview.reject({ response: { status: 400 } })
        })
        await act(async () => { oldErrorText.resolve('{"error":"Old render failed"}') })

        expect(container.querySelector('.error-banner')?.textContent ?? null)
            .toBe(outcome === 'success' ? null : 'admin.previewRenderError')
        if (outcome === 'success') {
            expect(container.querySelector('[data-preview-src]')?.getAttribute('data-preview-src'))
                .toBe('blob:new-preview')
        }
    })

    it('keeps a dirty buffer and accepts definitive save/reset responses after failed refreshes', async () => {
        const { container, client, editor } = await renderEditor()
        edit(editor, 'Draft PDF')
        await act(async () => { await client.invalidateQueries() })
        expect(editor.value).toBe('Draft PDF')

        await act(async () => click(container, 'common.save'))
        await vi.waitFor(() => expect(container.textContent).toContain('templates.source.customized'))
        api.fetch.mockRejectedValueOnce(new Error('refresh failed'))
        await act(async () => { await client.invalidateQueries() })
        expect(editor.value).toBe('Draft PDF')
        expect(container.textContent).toContain('templates.source.customized')

        await act(async () => click(container, 'admin.resetBuiltIn'))
        await act(async () => click(container.querySelector('[role="dialog"]')!, 'admin.resetBuiltIn'))
        await vi.waitFor(() => expect(container.textContent).toContain('templates.source.builtIn'))
        api.fetch.mockRejectedValueOnce(new Error('refresh failed'))
        await act(async () => { await client.invalidateQueries() })
        expect(editor.value).toBe('Default PDF')
        expect(container.textContent).toContain('templates.source.builtIn')
    })

    it('reports a failed save once and keeps the PDF draft', async () => {
        const { container, editor } = await renderEditor()
        edit(editor, 'Draft PDF')
        api.save.mockRejectedValueOnce(new Error('save failed'))
        await act(async () => click(container, 'common.save'))
        expect(container.querySelectorAll('.error-banner[role="alert"]')).toHaveLength(1)
        expect(toastSpy).not.toHaveBeenCalledWith('common.error', 'error')
        expect(editor.value).toBe('Draft PDF')
    })

    it('shows the server validation message without altering template variable names', async () => {
        const { container, editor } = await renderEditor()
        edit(editor, '{{ participant.emali }}')
        const draft = editor.value
        const message = 'Template rendering error: Unknown variable participant.emali.'
        api.save.mockRejectedValueOnce({ isAxiosError: true, response: { data: { error: message } } })
        await act(async () => { click(container, 'common.save') })
        expect(container.querySelector('[role="alert"]')?.textContent).toBe(message)
        expect(container.querySelectorAll('[role="alert"]')).toHaveLength(1)
        expect(editor.value).toBe(draft)
        expect(toastSpy).not.toHaveBeenCalled()
    })

})
