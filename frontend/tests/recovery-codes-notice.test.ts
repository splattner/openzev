import { act, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RecoveryCodesNotice } from '../src/features/account/RecoveryCodesNotice'
import { downloadBlob } from '../src/lib/downloadBlob'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/downloadBlob', () => ({ downloadBlob: vi.fn() }))

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); vi.clearAllMocks() })

const button = (root: ParentNode, label: string) => Array.from(root.querySelectorAll('button')).find((b) => b.textContent === label)!

describe('RecoveryCodesNotice', () => {
    it('renders newline-separated codes, downloads them and clears them', async () => {
        const onDismiss = vi.fn()
        const { container } = await renderWithProviders(createElement(RecoveryCodesNotice, { codes: ['aaaa-1111', 'bbbb-2222'], onDismiss }), cleanups)

        expect(container.querySelector('[data-testid="recovery-codes"]')!.textContent).toBe('aaaa-1111\nbbbb-2222')

        await act(async () => { button(container, 'account.mfa.download').click() })
        const [blob, name] = vi.mocked(downloadBlob).mock.calls[0]
        expect(name).toBe('openzev-recovery-codes.txt')
        expect(await (blob as Blob).text()).toBe('aaaa-1111\nbbbb-2222\n')

        await act(async () => { button(container, 'secretReveal.dismiss').click() })
        expect(onDismiss).toHaveBeenCalledOnce()
    })
})
