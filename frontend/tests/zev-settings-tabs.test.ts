import { waitForCondition } from './helpers/waitForCondition'
import { act, createElement, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { AppRoutes } from '../src/components/AppRoutes'
import { hasUnsavedZevSettingsDraft } from '../src/lib/zevUnsavedGuard'
import type { Zev, ZevInput } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function fixtureZev(overrides: Partial<Zev> = {}): Zev {
    return {
        id: 'z1',
        updated_at: '2026-01-01T00:00:00Z',
        name: 'First community',
        start_date: '2025-01-01',
        owner: 7,
        zev_type: 'vzev',
        postal_code: '8000',
        grid_operator: 'EWZ',
        grid_operator_elcom_id: null,
        tariff_source_url: '',
        grid_connection_point: '',
        billing_interval: 'monthly',
        invoice_prefix: 'INV',
        invoice_language: 'de',
        payment_term_days: 30,
        bank_iban: '',
        bank_name: '',
        vat_mode: 'not_registered',
        vat_number: '',
        itemize_tariff_bands: false,
        participant_invoice_access: false,
        notes: '',
        email_subject_template: 'Saved subject',
        email_body_template: '',
        local_tariff_notes: '',
        additional_contract_notes: '',
        ...overrides,
    }
}

const GLOBAL_TEMPLATE = {
    subject: 'Global subject',
    body: 'Global body',
    fields: [{
        group_key: 'invoiceEmail',
        group_title_key: null,
        fields: [{
            variable: '{invoice_number}',
            description_key: 'admin.emailTemplates.fields.invoiceNumber',
            example: 'INV-1',
        }],
    }],
}

const state = vi.hoisted(() => ({
    // A non-admin account managing the selected ZEV, or an admin.
    role: 'user',
    zev: {} as Zev,
    emailError: false,
    updateImpl: null as null | ((id: string, payload: Partial<ZevInput>) => Promise<Zev>),
}))

const updateSpy = vi.hoisted(() => vi.fn())
const emailSpy = vi.hoisted(() => vi.fn())
const toastSpy = vi.hoisted(() => vi.fn())

// The enrolment gate has its own tests (mfa.test.ts); the shell under test
// here is not what is being asserted about.
vi.mock('../src/components/MfaEnrolmentGate', () => ({
    MfaEnrolmentGate: ({ children }: { children: unknown }) => children,
}))

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ isAuthenticated: true, user: { role: state.role, id: 7 } }) }))
vi.mock('../src/components/Layout', () => ({ Layout: () => createElement(Outlet) }))
vi.mock('../src/lib/managedZev', () => {
    const context = {
        ManagedZevProvider: ({ children }: { children: ReactNode }) => children,
        useManagedZev: () => ({
            selectedZevId: state.zev?.id ?? '', selectedZev: state.zev ?? null, isLoading: false,
            relation: state.role === 'admin' ? 'admin' : 'manager',
        }),
    }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: toastSpy }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy' } }),
    toDayJsDateFormat: () => 'DD.MM.YYYY',
    formatShortDate: (d: string) => d,
}))
vi.mock('../src/lib/api/zev', () => ({
    fetchGridOperators: vi.fn().mockResolvedValue({ operators: [] }),
    fetchGridOperatorSuggestions: vi.fn().mockResolvedValue({ operators: [] }),
    updateZev: (...args: unknown[]) => updateSpy(...args),
    disableZev: vi.fn().mockResolvedValue({}),
    enableZev: vi.fn().mockResolvedValue({}),
}))
vi.mock('../src/lib/api/invoices', () => ({
    fetchEmailTemplate: (...args: unknown[]) => emailSpy(...args),
}))
vi.mock('../src/features/zev/ZevExportModal', () => ({ ZevExportModal: () => null }))
vi.mock('../src/pages/AdminAuditLogsPage', () => ({ AuditLogsPage: () => createElement('div', null, 'audit') }))
const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

beforeEach(() => {
    state.role = 'user'
    state.zev = fixtureZev()
    state.emailError = false
    state.updateImpl = async (id: string, payload: Partial<ZevInput>) => ({
        ...state.zev, ...payload, id, updated_at: '2026-01-02T00:00:00Z',
    }) as Zev
    updateSpy.mockImplementation((id: string, payload: Partial<ZevInput>) => state.updateImpl!(id, payload))
    emailSpy.mockImplementation(async (templateKey: string) => {
        if (state.emailError) {
            throw new Error('template down')
        }
        expect(templateKey).toBe('invoice_email')
        return GLOBAL_TEMPLATE
    })
    toastSpy.mockClear()
    updateSpy.mockClear()
    emailSpy.mockClear()
})

const routers = new WeakMap<QueryClient, ReturnType<typeof createMemoryRouter>>()

function element(route: string, client: QueryClient) {
    let router = routers.get(client)
    if (!router) {
        router = createMemoryRouter([{ path: '*', element: createElement(AppRoutes) }], { initialEntries: [route] })
        routers.set(client, router)
    }
    return createElement(QueryClientProvider, { client },
        createElement(MantineProvider, null, createElement(RouterProvider, { router })))
}

async function renderAt(route: string) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => { root.render(element(route, client)) })
    const field = route.endsWith('/billing') ? 'bank_iban'
        : route.endsWith('/documents') ? 'email_subject_template'
            : route === '/zev-settings' || route.endsWith('/general') ? 'name' : null
    await waitForCondition(() => field
        ? container.querySelector(`[data-zev-field="${field}"] input`) !== null
        : container.querySelector('[role="tab"]') !== null, 'settings panel', 5000)
    await act(async () => {})
    return { container, root, client, router: routers.get(client)! }
}

async function rerender(root: Root, route: string, client: QueryClient) {
    await act(async () => { root.render(element(route, client)) })
    await act(async () => { await routers.get(client)!.navigate(route, { replace: true }) })
    await act(async () => {})
}

function findTab(container: ParentNode, key: string) {
    return Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
        .find((button) => button.textContent === `pages.zevSettings.tabs.${key}`)!
}

async function clickTab(container: ParentNode, key: string) {
    await act(async () => { findTab(container, key).click() })
    await act(async () => {})
}

function setField(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
    const prototype = el instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype
    act(() => {
        Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(el, value)
        el.dispatchEvent(new Event('input', { bubbles: true }))
    })
}

async function submitForm(container: ParentNode) {
    await act(async () => {
        container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    await act(async () => {})
}

async function waitForText(container: ParentNode, text: string) {
    await waitForCondition(() => container.textContent?.includes(text) ?? false, `text ${text}`)
}

async function waitForPendingSave(container: ParentNode) {
    await waitForCondition(() => saveButton(container)?.disabled === true, 'pending save')
}

function saveButton(container: ParentNode) {
    return Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
        .find((button) => button.textContent === 'pages.zevSettings.saveChanges')
}

function saveBar(container: ParentNode) {
    return container.querySelector('.zev-settings-save-bar')
}

function discardButton(container: ParentNode) {
    return Array.from(container.querySelectorAll('button'))
        .find((button) => button.textContent === 'pages.zevSettings.discardChanges')
}

function generalInput(container: ParentNode) {
    return container.querySelector<HTMLInputElement>('[data-zev-field="name"] input')
}

function billingInput(container: ParentNode) {
    return container.querySelector<HTMLInputElement>('[data-zev-field="bank_iban"] input')
}

function subjectInput(container: ParentNode) {
    return container.querySelector<HTMLInputElement>('[data-zev-field="email_subject_template"] input')
}

describe('ZEV settings routed form', () => {
    it('preserves edits from the root through tabs and saves the shared form', async () => {
        const { container } = await renderAt('/zev-settings')
        setField(generalInput(container)!, 'Unsaved name')
        await clickTab(container, 'billingPayment')
        setField(billingInput(container)!, 'CH9300762011623852957')
        await clickTab(container, 'documentsEmails')
        expect(subjectInput(container)!.value).toBe('Saved subject')
        await clickTab(container, 'auditLog')
        expect(container.textContent).toContain('audit')
        await clickTab(container, 'billingPayment')
        expect(billingInput(container)!.value).toBe('CH9300762011623852957')
        await submitForm(container)
        expect(updateSpy).toHaveBeenCalledTimes(1)
        expect(updateSpy).toHaveBeenCalledWith('z1', expect.objectContaining({
            name: 'Unsaved name',
            bank_iban: 'CH9300762011623852957',
        }))
    })

    it('shows the save bar only while dirty and discards edits across tabs without a request', async () => {
        const { container } = await renderAt('/zev-settings/general')
        expect(saveBar(container)).toBeNull()
        expect(hasUnsavedZevSettingsDraft()).toBe(false)
        expect(saveButton(container)).toBeUndefined()
        setField(generalInput(container)!, 'Unsaved name')
        expect(saveBar(container)).not.toBeNull()
        expect(container.textContent).toContain('pages.zevSettings.unsavedChanges')
        expect(hasUnsavedZevSettingsDraft()).toBe(true)
        expect(saveButton(container)).toBeDefined()
        // Typing the value back reads as clean again — no manual flag.
        setField(generalInput(container)!, 'First community')
        expect(saveBar(container)).toBeNull()
        expect(hasUnsavedZevSettingsDraft()).toBe(false)
        expect(saveButton(container)).toBeUndefined()
        // Stage edits on two tabs, including an email reset, then discard.
        setField(generalInput(container)!, 'Unsaved name')
        await clickTab(container, 'documentsEmails')
        const reset = container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')!
        await act(async () => { reset.click() })
        await act(async () => { discardButton(container)!.click() })
        expect(updateSpy).not.toHaveBeenCalled()
        // Discard restores the saved subject, back in customized mode.
        expect(subjectInput(container)!.value).toBe('Saved subject')
        await clickTab(container, 'general')
        expect(generalInput(container)!.value).toBe('First community')
        expect(saveBar(container)).toBeNull()
    })

    it('clears a failed-save message when the draft returns to its baseline', async () => {
        state.updateImpl = async () => { throw new Error('save failed') }
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        await submitForm(container)
        await waitForText(container, 'pages.zevSettings.updateFailed')
        setField(generalInput(container)!, 'First community')
        await waitForCondition(() => saveBar(container) === null, 'clean save bar')
    })

    it('describes a live IBAN error with the same id as the save-time error', async () => {
        const { container } = await renderAt('/zev-settings/billing')
        setField(billingInput(container)!, 'invalid')
        expect(billingInput(container)?.getAttribute('aria-describedby')).toBe('zev-settings-field-bank_iban-error')
        expect(container.querySelector('#zev-settings-field-bank_iban-error')?.textContent)
            .toContain('pages.zevSettings.validation.invalidIban')
    })

    it('keeps a dirty draft on same-ZEV refresh but accepts fresh values when clean', async () => {
        const { container, root, client } = await renderAt('/zev-settings/general')
        // Discard with no server change restores the baseline, no request.
        setField(generalInput(container)!, 'Unsaved name')
        await act(async () => { discardButton(container)!.click() })
        expect(generalInput(container)!.value).toBe('First community')
        expect(updateSpy).not.toHaveBeenCalled()
        // A dirty draft survives a same-ZEV refresh carrying newer values.
        setField(generalInput(container)!, 'Unsaved name')
        state.zev = fixtureZev({ name: 'Server rename' })
        await rerender(root, '/zev-settings/general', client)
        expect(generalInput(container)!.value).toBe('Unsaved name')
        expect(container.textContent).toContain('pages.zevSettings.unsavedChanges')
        expect(hasUnsavedZevSettingsDraft()).toBe(true)
        // Discarding cleans the form, so the newer server values are accepted.
        await act(async () => { discardButton(container)!.click() })
        expect(generalInput(container)!.value).toBe('Server rename')
        expect(saveBar(container)).toBeNull()
        // A clean refresh keeps accepting fresh server values.
        state.zev = fixtureZev({ name: 'Server rename 2' })
        await rerender(root, '/zev-settings/general', client)
        expect(generalInput(container)!.value).toBe('Server rename 2')
    })

    it('accepts normalized server values on success and keeps edits on failure', async () => {
        const { container } = await renderAt('/zev-settings/billing')
        state.updateImpl = async (id, payload) => ({
            ...state.zev,
            ...payload,
            id,
            bank_iban: 'CH9300762011623852957',
        }) as Zev
        setField(billingInput(container)!, 'ch93 0076 2011 6238 5295 7')
        await submitForm(container)
        await waitForCondition(() => saveBar(container) === null, 'clean save bar')
        expect(billingInput(container)!.value).toBe('CH9300762011623852957')
        expect(toastSpy).toHaveBeenCalledWith('pages.zevSettings.updateSuccess', 'success')

        state.updateImpl = async () => { throw new Error('nope') }
        setField(billingInput(container)!, 'CH4431999123000889012')
        await submitForm(container)
        await waitForText(container, 'pages.zevSettings.updateFailed')
        expect(billingInput(container)!.value).toBe('CH4431999123000889012')
        expect(saveBar(container)).not.toBeNull()
        // Retry with a working backend persists the kept draft.
        state.updateImpl = async (id, payload) => ({ ...state.zev, ...payload, id }) as Zev
        await submitForm(container)
        expect(updateSpy).toHaveBeenLastCalledWith('z1', expect.objectContaining({
            bank_iban: 'CH4431999123000889012',
        }))
        await waitForCondition(() => saveBar(container) === null, 'clean save bar after retry')
    })

    it('blocks duplicate submits while pending and ignores late responses after a ZEV switch', async () => {
        const { container, root, client } = await renderAt('/zev-settings/general')
        let resolveSave!: (zev: Zev) => void
        state.updateImpl = () => new Promise<Zev>((resolve) => { resolveSave = resolve })
        setField(generalInput(container)!, 'Unsaved name')
        await submitForm(container)
        expect(updateSpy).toHaveBeenCalledTimes(1)
        // Pending state propagates asynchronously; wait for it first.
        await waitForPendingSave(container)
        expect(generalInput(container)?.disabled).toBe(true)
        await submitForm(container)
        expect(updateSpy).toHaveBeenCalledTimes(1)
        await act(async () => { resolveSave({ ...state.zev, name: 'Unsaved name' }) })
        await waitForCondition(() => saveBar(container) === null, 'clean save bar')

        // Second save in flight, then switch communities.
        state.updateImpl = () => new Promise<Zev>((resolve) => { resolveSave = resolve })
        setField(generalInput(container)!, 'Second edit')
        await submitForm(container)
        await waitForPendingSave(container)
        expect(updateSpy).toHaveBeenCalledTimes(2)
        state.zev = fixtureZev({ id: 'z2', name: 'Second community' })
        await rerender(root, '/zev-settings/general', client)
        expect(generalInput(container)!.value).toBe('Second community')
        expect(generalInput(container)!.disabled).toBe(false)
        setField(generalInput(container)!, 'New community edit')
        await act(async () => { resolveSave({ ...fixtureZev(), name: 'Second edit' }) })
        expect(generalInput(container)!.value).toBe('New community edit')
        expect(saveBar(container)).not.toBeNull()
        expect(container.querySelector('.error-banner')).toBeNull()
    })

    it('rejects a stale refetch after save but accepts a newer server revision', async () => {
        const { container, root, client } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Saved name')
        await submitForm(container)
        await waitForCondition(() => saveBar(container) === null, 'clean save bar')
        expect(generalInput(container)!.value).toBe('Saved name')

        state.zev = fixtureZev({ name: 'Stale name', updated_at: '2026-01-01T00:00:00Z' })
        await rerender(root, '/zev-settings/general', client)
        expect(generalInput(container)!.value).toBe('Saved name')

        state.zev = fixtureZev({ name: 'Later edit', updated_at: '2026-01-03T00:00:00Z' })
        await rerender(root, '/zev-settings/general', client)
        expect(generalInput(container)!.value).toBe('Later edit')
    })

    it('labels email sources independently and stages reset without a request', async () => {
        const { container } = await renderAt('/zev-settings/documents')
        // Subject customized, body on the platform default — independent badges.
        // The preview comes from the async template query; wait for it.
        await waitForCondition(
            () => container.textContent?.includes('Global body') ?? false,
            'body default preview',
        )
        const badges = Array.from(container.querySelectorAll('.badge')).map((badge) => badge.textContent)
        expect(badges).toContain('templates.source.zev')
        expect(badges).toContain('templates.source.platform')
        // Resetting the subject leaves the body alone and issues no request.
        await act(async () => {
            container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')!.click()
        })
        expect(container.querySelector('input')).toBeNull()
        expect(container.querySelector('[data-zev-field="email_subject_template"] .badge')?.textContent)
            .toBe('templates.source.zev')
        expect(container.querySelector('[data-zev-field="email_subject_template"] .template-source')?.textContent)
            .toContain('pages.zevSettings.emailInheritanceOnSave')
        expect(updateSpy).not.toHaveBeenCalled()
        await act(async () => { discardButton(container)!.click() })
        expect(subjectInput(container)!.value).toBe('Saved subject')
        expect(container.querySelector('[data-zev-field="email_subject_template"] .badge')?.textContent)
            .toBe('templates.source.zev')
        await act(async () => {
            container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')!.click()
        })
        // Customize seeds the editor with the platform text for real editing.
        await act(async () => {
            container.querySelector('button[aria-label="pages.zevSettings.emailCustomizeSubject"]')!.click()
        })
        expect(subjectInput(container)!.value).toBe('Global subject')
        expect(container.textContent).toContain('templates.source.zev')
        await act(async () => {
            container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')!.click()
        })
        await submitForm(container)
        expect(updateSpy).toHaveBeenCalledWith('z1', expect.objectContaining({ email_subject_template: '' }))
        await waitForCondition(() => saveBar(container) === null, 'saved email reset')
        expect(container.querySelector('[data-zev-field="email_subject_template"] .badge')?.textContent)
            .toBe('templates.source.platform')
    })

    it('returns an inherited field to its preview after discarding customization', async () => {
        const { container } = await renderAt('/zev-settings/documents')
        await waitForCondition(() => container.textContent?.includes('Global body') ?? false, 'body default preview')
        await act(async () => {
            container.querySelector<HTMLButtonElement>('button[aria-label="pages.zevSettings.emailCustomizeBody"]')!.click()
        })
        const editor = container.querySelector<HTMLTextAreaElement>('[data-zev-field="email_body_template"] textarea')!
        setField(editor, 'Draft body')
        await act(async () => { discardButton(container)!.click() })
        expect(container.querySelector('[data-zev-field="email_body_template"] textarea')).toBeNull()
        expect(container.querySelector('[data-zev-field="email_body_template"] .zev-email-default-preview')?.textContent).toBe('Global body')
        expect(updateSpy).not.toHaveBeenCalled()
    })

    it('shows the platform default after saving an emptied custom editor', async () => {
        const { container } = await renderAt('/zev-settings/documents')
        setField(subjectInput(container)!, '')
        await submitForm(container)
        await waitForCondition(() => saveBar(container) === null, 'clean save bar')
        expect(subjectInput(container)).toBeNull()
        expect(container.querySelector('button[aria-label="pages.zevSettings.emailCustomizeSubject"]')).not.toBeNull()
    })

    it('loads the platform fallback for owners and stays editable when it fails', async () => {
        const { container } = await renderAt('/zev-settings/documents')
        expect(emailSpy).toHaveBeenCalledWith('invoice_email')
        await waitForCondition(
            () => container.textContent?.includes('Global body') ?? false,
            'owner fallback preview',
        )

        state.emailError = true
        const { container: failed } = await renderAt('/zev-settings/documents')
        await waitForText(failed, 'common.error')
        await clickTab(failed, 'general')
        const input = generalInput(failed)!
        setField(input, 'Still editable')
        await submitForm(failed)
        expect(updateSpy).toHaveBeenCalledWith('z1', expect.objectContaining({ name: 'Still editable' }))
    })

    it('locks every control for disabled-ZEV owners but not for admins', async () => {
        state.zev = fixtureZev({ disabled_at: '2026-01-01T00:00:00Z' })
        const { container } = await renderAt('/zev-settings/general')
        expect(container.querySelector('.warning-banner')?.getAttribute('role')).toBe('status')
        expect(generalInput(container)?.disabled).toBe(true)
        expect(saveButton(container)).toBeUndefined()
        await clickTab(container, 'documentsEmails')
        const subject = subjectInput(container)!
        expect(subject.disabled).toBe(true)
        expect(container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')).toBeNull()

        state.role = 'admin'
        const { container: admin } = await renderAt('/zev-settings/general')
        expect(generalInput(admin)?.disabled).toBe(false)
    })

    it('blocks an invalid save on the same tab and focuses the field', async () => {
        const { container } = await renderAt('/zev-settings/billing')
        setField(billingInput(container)!, 'not-an-iban')
        await submitForm(container)
        expect(updateSpy).not.toHaveBeenCalled()
        expect(document.activeElement).toBe(billingInput(container))
        expect(container.textContent).toContain('pages.zevSettings.validation.invalidIban')
        expect(saveBar(container)).not.toBeNull()
        // Editing the field drops its stale message; a fixed value saves.
        setField(billingInput(container)!, 'CH9300762011623852957')
        expect(container.textContent).not.toContain('pages.zevSettings.validation.invalidIban')
        await submitForm(container)
        expect(updateSpy).toHaveBeenCalledTimes(1)
    })

    it('jumps to the invalid field on another tab when saving', async () => {
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, '')
        await clickTab(container, 'billingPayment')
        await submitForm(container)
        expect(updateSpy).not.toHaveBeenCalled()
        // Back on General with the name focused and flagged.
        expect(generalInput(container)).not.toBeNull()
        expect(document.activeElement).toBe(generalInput(container))
        expect(container.textContent).toContain('pages.zevSettings.validation.requiredName')
    })

    it('routes server-side field errors to their tab and focuses the field', async () => {
        state.updateImpl = async () => {
            throw { isAxiosError: true, response: { data: { bank_iban: ['Enter a valid IBAN.'] } } }
        }
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        await submitForm(container)
        expect(updateSpy).toHaveBeenCalledTimes(1)
        // The billing field opens with its server message, focused.
        await waitForCondition(() => billingInput(container) !== null, 'billing tab after field error')
        expect(document.activeElement).toBe(billingInput(container))
        expect(container.textContent).toContain('Enter a valid IBAN.')
        expect(container.querySelector('.error-banner')).not.toBeNull()
    })

    it.each([
        ['documents', 'email_subject_template', 'input'],
        ['general', 'email_subject_template', 'input'],
        ['documents', 'email_body_template', 'textarea'],
        ['general', 'email_body_template', 'textarea'],
    ])('focuses the enabled %s → %s editor after a rejected save', async (tab, field, selector) => {
        state.zev = fixtureZev({ email_body_template: 'Saved body' })
        let rejectSave!: (reason: unknown) => void
        state.updateImpl = () => new Promise<Zev>((_resolve, reject) => { rejectSave = reject })
        const { container } = await renderAt(`/zev-settings/${tab}`)
        const edited = tab === 'general' ? generalInput(container)! : subjectInput(container)!
        setField(edited, 'Unsaved edit')
        await act(async () => { saveButton(container)!.click() })
        await waitForPendingSave(container)
        expect(edited.disabled).toBe(true)
        await act(async () => {
            rejectSave({ isAxiosError: true, response: { data: { [field]: ['Invalid email text.'] } } })
        })
        await waitForCondition(() => {
            const editor = container.querySelector(`[data-zev-field="${field}"] ${selector}`)
            return editor !== null && document.activeElement === editor
        }, 'focus on the invalid email editor')
        const editor = document.activeElement as HTMLInputElement | HTMLTextAreaElement
        expect(editor.disabled).toBe(false)
        expect(editor.getAttribute('aria-invalid')).toBe('true')
        expect(document.getElementById(editor.getAttribute('aria-describedby')!)?.textContent)
            .toBe('Invalid email text.')
        expect(subjectInput(container)!.value).toBe(tab === 'general' ? 'Saved subject' : 'Unsaved edit')
    })

    it.each([
        ['tariff_source_url', 'tariff_source_url', 'input'],
        ['grid_operator_elcom_id', 'grid_operator', 'input'],
        ['invoice_prefix', 'invoice_prefix', 'input'],
        ['itemize_tariff_bands', 'itemize_tariff_bands', 'input'],
        ['notes', 'notes', 'textarea'],
        ['start_date', 'start_date', 'button[data-dates-input]'],
    ])('shows and associates a server %s error with its editable control', async (field, anchor, selector) => {
        state.updateImpl = async () => {
            throw { isAxiosError: true, response: { data: { [field]: ['Correct this value.'] } } }
        }
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        await submitForm(container)
        await waitForCondition(() => {
            const control = container.querySelector(`[data-zev-field="${anchor}"] ${selector}`)
            return control !== null && document.activeElement === control
        }, 'focus on the field with a server error')
        const control = document.activeElement!
        expect(control.getAttribute('aria-invalid')).toBe('true')
        const describedBy = control.getAttribute('aria-describedby')!.split(' ')
        expect(describedBy.some((id) => document.getElementById(id)?.textContent === 'Correct this value.')).toBe(true)
        if (field === 'tariff_source_url') {
            setField(control as HTMLInputElement, 'https://example.com/tariffs.csv')
            expect(control.getAttribute('aria-invalid')).not.toBe('true')
            expect(container.querySelector('#zev-settings-field-tariff_source_url-error')).toBeNull()
        }
    })

    it('shows a server email error beside its default field', async () => {
        state.zev = fixtureZev({ email_subject_template: '' })
        state.updateImpl = async () => {
            throw { isAxiosError: true, response: { data: { email_subject_template: ['Invalid subject.'] } } }
        }
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        await submitForm(container)
        await waitForText(container, 'Invalid subject.')
        const customize = container.querySelector<HTMLButtonElement>(
            'button[aria-label="pages.zevSettings.emailCustomizeSubject"]',
        )!
        expect(customize.getAttribute('aria-describedby')).toBe('zev-settings-email-subject-error')
        expect(container.querySelector('#zev-settings-email-subject-error')?.textContent).toBe('Invalid subject.')
        expect(document.activeElement).toBe(customize)
    })

    it('keeps save actions on audit and export while a draft exists', async () => {
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        await clickTab(container, 'exportTransfer')
        expect(saveBar(container)).not.toBeNull()
        expect(saveButton(container)).toBeDefined()
        await clickTab(container, 'auditLog')
        expect(container.textContent).toContain('audit')
        expect(saveBar(container)).not.toBeNull()
        // No detour link: the bar saves the whole draft in place.
        expect(container.textContent).not.toContain('pages.zevSettings.unsavedNoticeLink')
        await act(async () => { saveButton(container)!.click() })
        expect(updateSpy).toHaveBeenCalledTimes(1)
        expect(updateSpy).toHaveBeenCalledWith('z1', expect.objectContaining({ name: 'Unsaved name' }))
        await waitForCondition(() => saveBar(container) === null, 'clean save bar after audit save')
    })

    it('associates the save action with the active form', async () => {
        const { container } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        expect(container.querySelector('form')?.noValidate).toBe(true)
        expect(saveButton(container)?.type).toBe('submit')
        expect(saveButton(container)?.form).toBe(container.querySelector('form'))
        await clickTab(container, 'auditLog')
        expect(saveButton(container)?.type).toBe('button')
    })

    it('cancels browser unloads only while dirty', async () => {
        const { container } = await renderAt('/zev-settings/general')
        const clean = new Event('beforeunload', { cancelable: true })
        window.dispatchEvent(clean)
        expect(clean.defaultPrevented).toBe(false)
        setField(generalInput(container)!, 'Unsaved name')
        const dirty = new Event('beforeunload', { cancelable: true })
        window.dispatchEvent(dirty)
        expect(dirty.defaultPrevented).toBe(true)
    })

    it('confirms before leaving settings with an unsaved draft', async () => {
        const { container, router } = await renderAt('/zev-settings/general')
        setField(generalInput(container)!, 'Unsaved name')
        await act(async () => { void router.navigate('/participants') })
        expect(router.state.location.pathname).toBe('/zev-settings/general')
        expect(container.querySelector('[role="dialog"]')?.textContent)
            .toContain('pages.zevSettings.unsavedGuardLeaveMessage')
        await act(async () => {
            Array.from(container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'))
                .find((button) => button.textContent === 'common.cancel')!.click()
        })
        expect(generalInput(container)?.value).toBe('Unsaved name')
        expect(router.state.location.pathname).toBe('/zev-settings/general')
        await act(async () => { void router.navigate('/participants') })
        await act(async () => {
            Array.from(container.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'))
                .find((button) => button.textContent === 'pages.zevSettings.leaveWithoutSaving')!.click()
        })
        await waitForCondition(() => router.state.location.pathname === '/participants', 'navigation after confirmation')
    })
})
