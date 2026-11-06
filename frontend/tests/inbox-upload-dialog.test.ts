import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flush } from './pdf-test-utils'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/inbox', () => ({ uploadInboxDocument: vi.fn() }))

import { UploadDocumentDialog } from '../src/features/inbox/UploadDocumentDialog'
import * as inboxApi from '../src/lib/api/inbox'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function render() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const participants = [{ id: 'p1', first_name: 'Anna', last_name: 'A' }] as never
    act(() => root.render(createElement(
        MantineProvider, null,
        createElement(
            QueryClientProvider, { client: new QueryClient() },
            createElement(UploadDocumentDialog, { isOpen: true, onClose: vi.fn(), zevId: 'z1', participants }),
        ),
    )))
    return () => { act(() => root.unmount()); container.remove() }
}

const submit = () => document.querySelector('button[type="submit"]') as HTMLButtonElement
const text = () => document.body.textContent ?? ''

describe('UploadDocumentDialog', () => {
    afterEach(() => vi.clearAllMocks())

    it('keeps the submit button live and names what is missing, by the field, after the first submit', async () => {
        const unmount = render()
        expect(submit().disabled).toBe(false)
        expect(text()).not.toContain('inbox.upload.error.title')

        await act(async () => { submit().click() })
        await flush()

        expect(text()).toContain('inbox.upload.error.title')
        expect(text()).toContain('inbox.upload.error.file')
        expect(inboxApi.uploadInboxDocument).not.toHaveBeenCalled()
        unmount()
    })

    it('asks for at least one participant when only chosen ones should receive it', async () => {
        const unmount = render()
        const selected = document.querySelectorAll('input[type="radio"]')[1] as HTMLInputElement
        await act(async () => { selected.click() })

        await act(async () => { submit().click() })
        await flush()

        expect(text()).toContain('inbox.upload.error.audience')
        unmount()
    })
})
