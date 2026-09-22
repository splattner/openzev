import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { ToastProvider } from '../src/lib/toast'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ZevListPage } from '../src/pages/ZevListPage'
import type { Zev } from '../src/types/api'

/** Admin ZEV creation wizard — bank fields. */
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        user: { id: 1, username: 'admin', email: 'a@x.ch', first_name: '', last_name: '', role: 'admin' },
    }),
}))

const mockSetSelectedZevId = vi.fn()
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: '', setSelectedZevId: mockSetSelectedZevId }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router-dom')>()),
    useNavigate: () => mockNavigate,
}))

const ZEV = {
    id: 'z1',
    name: 'Muster ZEV',
    start_date: '2026-01-01',
    owner: 9,
    zev_type: 'zev',
    grid_operator: '',
    billing_interval: 'monthly',
} as Zev

const createZevWithOwnerMock = vi.fn()
vi.mock('../src/lib/api/zev', async (importOriginal) => ({
    ...(await importOriginal<Record<string, unknown>>()),
    fetchZevs: () => Promise.resolve([ZEV]),
    fetchParticipants: () => Promise.resolve([]),
    fetchGridOperators: () => Promise.resolve({ operators: [], source: '', cube: '', licence: '', period: '', fetched_on: '' }),
    createZevWithOwner: (...args: unknown[]) => createZevWithOwnerMock(...args),
    updateZev: vi.fn(),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: () => Promise.resolve([]),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/components/ConfirmDialog', () => ({
    ConfirmDialog: () => null,
    useConfirmDialog: () => ({
        dialog: null,
        confirm: vi.fn(),
        handleConfirm: vi.fn(),
        handleCancel: vi.fn(),
        isLoading: false,
    }),
}))

/** React 19 tracks input values, so assignments must go through the native setter. */
function setInputValue(input: HTMLInputElement, value: string) {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
}

async function flush() {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0))
    })
}

async function renderZevListPage() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                null,
                createElement(
                    MantineProvider,
                    null,
                    createElement(
                        ToastProvider,
                        null,
                        createElement(
                            QueryClientProvider,
                            { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                            createElement(ZevListPage),
                        ),
                    ),
                ),
            ),
        )
    })
    await flush()
    return { container, root }
}

function clickButton(container: HTMLElement, label: string): HTMLButtonElement {
    const button = Array.from(container.querySelectorAll('button')).find((b) =>
        b.textContent?.includes(label),
    )
    if (!button) throw new Error(`button not found: ${label}`)
    return button as HTMLButtonElement
}

async function fillRequiredStepOneInputs(container: HTMLElement) {
    // start_date is prefilled with today; zev_type/billing_interval have defaults.
    const nameInput = container.querySelector<HTMLInputElement>('input[name="name"]')!
    setInputValue(nameInput, 'IBAN ZEV')
    await flush()
}

async function fillRequiredOwnerInputs(container: HTMLElement) {
    const firstName = container.querySelector<HTMLInputElement>('input[name="first_name"]')!
    const lastName = container.querySelector<HTMLInputElement>('input[name="last_name"]')!
    const email = container.querySelector<HTMLInputElement>('input[name="email"]')!
    setInputValue(firstName, 'Oscar')
    setInputValue(lastName, 'Owner')
    setInputValue(email, 'oscar@example.com')
    await flush()
}

async function fillMeterId(container: HTMLElement) {
    const meterIdInput = container.querySelector<HTMLInputElement>('input[name="meter_id"]')!
    setInputValue(meterIdInput, 'METER-1')
    await flush()
}

async function walkToReview(container: HTMLElement) {
    await act(async () => {
        clickButton(container, 'pages.zevs.wizard.next').click()
    })
    await fillRequiredOwnerInputs(container)
    await act(async () => {
        clickButton(container, 'pages.zevs.wizard.next').click()
    })
    await fillMeterId(container)
    await act(async () => {
        clickButton(container, 'pages.zevs.wizard.next').click()
    })
}

describe('ZevListPage creation wizard — bank fields', () => {
    beforeEach(() => {
        createZevWithOwnerMock.mockClear()
    })

    it('sends bank_iban and bank_name to createZevWithOwner', async () => {
        createZevWithOwnerMock.mockResolvedValue({
            zev: { id: 'z-new', name: 'IBAN ZEV' },
            owner: { id: 2, username: 'owa', temporary_password: 'pw' },
            owner_participant_id: 'p1',
            metering_points: [{ id: 'm1', meter_id: 'METER-1' }],
        })
        const { container, root } = await renderZevListPage()
        try {
            await act(async () => {
                clickButton(container, 'pages.zevs.newZev').click()
            })
            await fillRequiredStepOneInputs(container)
            await act(async () => {
                clickButton(container, 'pages.zevs.wizard.next').click()
            })
            await fillRequiredOwnerInputs(container)
            setInputValue(container.querySelector<HTMLInputElement>('input[name="address_line1"]')!, 'Example 1')
            setInputValue(container.querySelector<HTMLInputElement>('input[name="postal_code"]')!, '8000')
            setInputValue(container.querySelector<HTMLInputElement>('input[name="city"]')!, 'Zurich')
            const ibanInput = container.querySelector<HTMLInputElement>('input[name="bank_iban"]')!
            const bankNameInput = container.querySelector<HTMLInputElement>('input[name="bank_name"]')!
            expect(ibanInput).not.toBe(null)
            expect(bankNameInput).not.toBe(null)
            setInputValue(ibanInput, 'CH93 0076 2011 6238 5295 7')
            setInputValue(bankNameInput, 'Demo Bank')
            await act(async () => {
                clickButton(container, 'pages.zevs.wizard.next').click()
            })
            await fillMeterId(container)
            await act(async () => {
                clickButton(container, 'pages.zevs.wizard.next').click()
            })

            const review = Array.from(container.querySelectorAll('.card')).find((card) =>
                card.textContent?.includes('pages.zevs.wizard.reviewIban'),
            )
            if (!review) throw new Error('review card not found')
            expect(review.textContent).toContain('pages.zevs.wizard.reviewIban')
            expect(review.textContent).toContain('CH93 0076 2011 6238 5295 7')

            await act(async () => {
                clickButton(container, 'pages.zevs.wizard.createZev').click()
            })
            await flush()

            expect(createZevWithOwnerMock).toHaveBeenCalledTimes(1)
            const payload = createZevWithOwnerMock.mock.calls[0][0]
            expect(payload.bank_iban).toBe('CH9300762011623852957')
            expect(payload.bank_name).toBe('Demo Bank')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('sends empty bank fields and shows the review dash when left blank', async () => {
        createZevWithOwnerMock.mockResolvedValue({
            zev: { id: 'z-new', name: 'Blank ZEV' },
            owner: { id: 3, username: 'owb', temporary_password: 'pw' },
            owner_participant_id: 'p2',
            metering_points: [{ id: 'm2', meter_id: 'METER-2' }],
        })
        const { container, root } = await renderZevListPage()
        try {
            await act(async () => {
                clickButton(container, 'pages.zevs.newZev').click()
            })
            await fillRequiredStepOneInputs(container)

            await walkToReview(container)

            const review = Array.from(container.querySelectorAll('.card')).find((card) =>
                card.textContent?.includes('pages.zevs.wizard.reviewIban'),
            )
            if (!review) throw new Error('review card not found')
            expect(review.textContent).toContain('pages.zevs.wizard.reviewIban')
            expect(review.textContent).toContain('–')

            await act(async () => {
                clickButton(container, 'pages.zevs.wizard.createZev').click()
            })
            await flush()

            expect(createZevWithOwnerMock).toHaveBeenCalledTimes(1)
            const payload = createZevWithOwnerMock.mock.calls[0][0]
            expect(payload.bank_iban).toBe('')
            expect(payload.bank_name).toBe('')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('rejects an invalid IBAN on the owner step and does not advance', async () => {
        const { container, root } = await renderZevListPage()
        try {
            await act(async () => { clickButton(container, 'pages.zevs.newZev').click() })
            await fillRequiredStepOneInputs(container)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            await fillRequiredOwnerInputs(container)
            setInputValue(container.querySelector<HTMLInputElement>('input[name="address_line1"]')!, 'Example 1')
            setInputValue(container.querySelector<HTMLInputElement>('input[name="postal_code"]')!, '8000')
            setInputValue(container.querySelector<HTMLInputElement>('input[name="city"]')!, 'Zurich')
            setInputValue(container.querySelector<HTMLInputElement>('input[name="bank_iban"]')!, 'not-an-iban')
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            await flush()
            const errorText = Array.from(container.querySelectorAll('.error-banner, [data-testid="error"]')).map((el) => el.textContent).join('\n')
            expect(errorText || Array.from(container.querySelectorAll('.card, p, div')).map((el) => el.textContent).join('\n')).toContain('pages.zevs.validation.invalidIban')
            expect(container.querySelector<HTMLInputElement>('input[name="bank_iban"]')).not.toBe(null)
            expect(createZevWithOwnerMock).not.toHaveBeenCalled()
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('rejects a bank IBAN without a payment recipient address and does not advance', async () => {
        const { container, root } = await renderZevListPage()
        try {
            await act(async () => { clickButton(container, 'pages.zevs.newZev').click() })
            await fillRequiredStepOneInputs(container)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            await fillRequiredOwnerInputs(container)
            setInputValue(container.querySelector<HTMLInputElement>('input[name="bank_iban"]')!, 'CH9300762011623852957')
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            await flush()
            const errorText = Array.from(container.querySelectorAll('.error-banner, [data-testid="error"]')).map((el) => el.textContent).join('\n')
            const fullText = errorText || Array.from(container.querySelectorAll('.card, p, div')).map((el) => el.textContent).join('\n')
            expect(fullText).toMatch(/pages\.zevs\.validation\.ownerAddressRequiredForIban|pages\.zevs\.validation\.ownerPostalCodeRequiredForIban|pages\.zevs\.validation\.ownerCityRequiredForIban/)
            expect(createZevWithOwnerMock).not.toHaveBeenCalled()
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('retains typed meter text when Advancing (type then Weiter)', async () => {
        createZevWithOwnerMock.mockResolvedValue({
            zev: { id: 'z-x', name: 'Meter ZEV' },
            owner: { id: 9, username: 'met', temporary_password: 'pw' },
            owner_participant_id: 'p9',
            metering_points: [{ id: 'm9', meter_id: 'METER-NEW' }],
        })
        const { container, root } = await renderZevListPage()
        try {
            await act(async () => { clickButton(container, 'pages.zevs.newZev').click() })
            await fillRequiredStepOneInputs(container)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            await fillRequiredOwnerInputs(container)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            // Step 3 auto-opens the metering point editor. Enter an ID then click Weiter
            // immediately — without an explicit save — to expose stale-draft bugs.
            const meterIdInput = container.querySelector<HTMLInputElement>('input[name="meter_id"]')!
            setInputValue(meterIdInput, 'METER-NEW')
            // No explicit "save": Weiter should fold the editor draft into the payload.
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            const review = Array.from(container.querySelectorAll('.card')).find((card) =>
                card.textContent?.includes('pages.zevs.wizard.reviewMeteringPoints'),
            )
            if (!review) throw new Error('review card not found')
            expect(review.textContent).toContain('METER-NEW')
            expect(createZevWithOwnerMock).not.toHaveBeenCalled() // still review step (next created below)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.createZev').click() })
            await flush()
            expect(createZevWithOwnerMock).toHaveBeenCalledTimes(1)
            const payload = createZevWithOwnerMock.mock.calls[0][0]
            expect(payload.metering_points.map((p: { meter_id: string }) => p.meter_id)).toContain('METER-NEW')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('edits the correct metering point and deletes without row-shift side effects', async () => {
        const { container, root } = await renderZevListPage()
        try {
            await act(async () => { clickButton(container, 'pages.zevs.newZev').click() })
            await fillRequiredStepOneInputs(container)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            await fillRequiredOwnerInputs(container)
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            const meterIdInput = container.querySelector<HTMLInputElement>('input[name="meter_id"]')!
            setInputValue(meterIdInput, 'METER-A')
            await act(async () => { clickButton(container, 'pages.zevs.wizard.addMeteringPoint').click() })
            setInputValue(container.querySelector<HTMLInputElement>('input[name="meter_id"]')!, 'METER-B')
            await act(async () => { clickButton(container, 'pages.zevs.wizard.next').click() })
            const review = Array.from(container.querySelectorAll('.card')).find((card) =>
                card.textContent?.includes('pages.zevs.wizard.reviewMeteringPoints'),
            )
            expect(review?.textContent).toContain('METER-A')
            expect(review?.textContent).toContain('METER-B')
            await act(async () => { clickButton(container, 'pages.zevs.wizard.back').click() })
            await flush()
            const meterRows = container.querySelectorAll('[data-testid="wizard-metering-points-table"] table tbody tr')
            expect(meterRows.length).toBe(2)
            const meterTableDeleteButtons = Array.from(container.querySelectorAll('[data-testid="wizard-metering-points-table"] tbody button')).filter((b) =>
                b.textContent?.includes('common.delete'),
            )
            expect(meterTableDeleteButtons.length).toBe(2)
            await act(async () => { meterTableDeleteButtons[0].click() })
            await flush()
            const rowsAfterDelete = container.querySelectorAll('[data-testid="wizard-metering-points-table"] table tbody tr')
            expect(rowsAfterDelete.length).toBe(1)
            expect(rowsAfterDelete[0].textContent).toContain('METER-B')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })
})
