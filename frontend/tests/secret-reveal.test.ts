import { act, createElement, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SecretReveal } from '../src/components/SecretReveal'
import { copyToClipboard } from '../src/lib/clipboard'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/clipboard', () => ({ copyToClipboard: vi.fn() }))

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); vi.clearAllMocks() })

const button = (root: ParentNode, label: string) =>
    Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent?.includes(label))
const click = async (element: HTMLElement) => { await act(async () => { element.click() }) }
const reveal = (props: Record<string, unknown> = {}) =>
    createElement(SecretReveal, { secret: 'oza_x_y', title: 'Push token', body: 'Shown only once.', ...props })

describe('SecretReveal', () => {
    it('shows the title, the secret, the warning and the hints', async () => {
        const { container } = await renderWithProviders(createElement(SecretReveal, { secret: 'oza_x_y', title: 'Push token', body: 'Shown only once.' }, createElement('p', null, 'extra hint')), cleanups)

        expect(container.querySelector('[data-testid="secret-reveal"]')!.textContent).toBe('oza_x_y')
        expect(container.textContent).toContain('Push token')
        expect(container.textContent).toContain('extra hint')
    })

    it('makes only the warning a live region, with no buttons in it', async () => {
        const { container } = await renderWithProviders(reveal({ onDismiss: vi.fn() }), cleanups)

        const regions = container.querySelectorAll('[role="alert"], [role="status"], [aria-live]')
        expect(regions).toHaveLength(1)
        expect(regions[0].textContent).toBe('Shown only once.')
        expect(regions[0].querySelector('button')).toBeNull()
    })

    it('names Copy after the value it copies', async () => {
        const { container } = await renderWithProviders(reveal(), cleanups)

        const copy = button(container, 'common.copy')!
        const names = copy.getAttribute('aria-labelledby')!.split(' ').map((id) => document.getElementById(id)!.textContent)
        expect(names).toEqual(['common.copy', 'Push token'])
    })

    it('copies the value shown now, also after a new secret replaced it, and reports each result', async () => {
        vi.mocked(copyToClipboard).mockResolvedValueOnce(true).mockResolvedValueOnce(false)
        function Host() {
            const [secret, setSecret] = useState('first')
            return createElement('div', null,
                createElement(SecretReveal, { secret, title: 'Codes', body: 'Once.' }),
                createElement('button', { type: 'button', onClick: () => setSecret('second') }, 'regenerate'))
        }
        const { container } = await renderWithProviders(createElement(Host), cleanups)

        await click(button(container, 'common.copy')!)
        expect(copyToClipboard).toHaveBeenLastCalledWith('first')
        expect(pushToast).toHaveBeenLastCalledWith('common.copied', 'success')

        await click(button(container, 'regenerate')!)
        await click(button(container, 'common.copy')!)
        expect(copyToClipboard).toHaveBeenLastCalledWith('second')
        expect(pushToast).toHaveBeenLastCalledWith('common.copyFailed', 'error')
        // The label never claims a copy, so a new or failed one cannot inherit a success.
        expect(button(container, 'common.copy')!.textContent).toBe('common.copy')
        expect(container.querySelector('[data-testid="secret-reveal"]')!.textContent).toBe('second')
    })

    it('offers a clear action on a page and none in a dialog', async () => {
        const onDismiss = vi.fn()
        const page = await renderWithProviders(reveal({ onDismiss }), cleanups)
        await click(button(page.container, 'secretReveal.dismiss')!)
        expect(onDismiss).toHaveBeenCalledOnce()

        const dialog = await renderWithProviders(reveal(), cleanups)
        expect(button(dialog.container, 'secretReveal.dismiss')).toBeUndefined()
    })

    it('starts on Copy when the control that created the secret is gone', async () => {
        const { container } = await renderWithProviders(reveal(), cleanups)

        expect(document.activeElement).toBe(button(container, 'common.copy'))
    })

    it('leaves focus alone when it is still somewhere', async () => {
        const elsewhere = document.createElement('button')
        document.body.append(elsewhere)
        elsewhere.focus()
        await renderWithProviders(reveal(), cleanups)

        expect(document.activeElement).toBe(elsewhere)
        elsewhere.remove()
    })
})
