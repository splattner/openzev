import { act, createElement } from 'react'
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
    Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent?.includes(label))!

describe('SecretReveal', () => {
    it('shows the secret once, copies it and dismisses', async () => {
        vi.mocked(copyToClipboard).mockResolvedValue(true)
        const onDismiss = vi.fn()
        const { container } = await renderWithProviders(
            createElement(SecretReveal, { secret: 'oza_x_y', onDismiss }, createElement('p', null, 'extra hint')), cleanups)

        expect(container.querySelector('[data-testid="secret-reveal"]')!.textContent).toBe('oza_x_y')
        expect(container.textContent).toContain('secretReveal.body')
        expect(container.textContent).toContain('extra hint')

        await act(async () => { button(container, 'secretReveal.copy').click() })
        expect(copyToClipboard).toHaveBeenCalledWith('oza_x_y')
        expect(container.textContent).toContain('secretReveal.copied')

        await act(async () => { button(container, 'secretReveal.dismiss').click() })
        expect(onDismiss).toHaveBeenCalledOnce()
    })

    it('says so when copying fails, and does not claim success', async () => {
        vi.mocked(copyToClipboard).mockResolvedValue(false)
        const { container } = await renderWithProviders(createElement(SecretReveal, { secret: 's', onDismiss: vi.fn() }), cleanups)

        await act(async () => { button(container, 'secretReveal.copy').click() })

        expect(pushToast).toHaveBeenCalledWith('secretReveal.copyFailed', 'error')
        expect(container.textContent).not.toContain('secretReveal.copied')
    })

    it('lets a caller keep its own wording and test id', async () => {
        const { container } = await renderWithProviders(createElement(SecretReveal, {
            secret: 's', onDismiss: vi.fn(), testId: 'my-secret', title: 'T', body: 'B', labels: { copy: 'Kopieren', dismiss: 'Fertig' },
        }), cleanups)

        expect(container.querySelector('[data-testid="my-secret"]')).not.toBeNull()
        expect(container.textContent).toContain('T')
        expect(container.textContent).toContain('B')
        expect(button(container, 'Kopieren')).toBeDefined()
        expect(button(container, 'Fertig')).toBeDefined()
    })
})
