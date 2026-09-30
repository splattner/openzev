import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))

import { MeteringPointFormModal } from '../src/features/meteringPoints/MeteringPointFormModal'
import { defaultMeteringPointForm } from '../src/features/meteringPoints/useMeteringPointForms'
import type { MeteringPointInput } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function Harness({ initial }: { initial: MeteringPointInput }) {
    const [form, setForm] = useState<MeteringPointInput>(initial)
    return createElement(
        MantineProvider,
        null,
        createElement(MeteringPointFormModal, {
            isOpen: true,
            title: 'Edit metering point',
            submitLabel: 'Save',
            form,
            isPending: false,
            onClose: () => undefined,
            onSubmit: (event) => event.preventDefault(),
            setForm,
        }),
    )
}

function setSelectValue(select: HTMLSelectElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    setter.call(select, value)
    select.dispatchEvent(new Event('change', { bubbles: true }))
}

describe('MeteringPointFormModal behind-meter-generation checkbox', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
    })

    function renderForm(initial: MeteringPointInput) {
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
        act(() => {
            root.render(createElement(Harness, { initial }))
        })
    }

    it('hides the checkbox for a consumption meter', () => {
        renderForm({ ...defaultMeteringPointForm(), meter_type: 'consumption' })
        expect(container.textContent).not.toContain('pages.meteringPoints.form.behindMeterGeneration')
    })

    it('shows the checkbox for bidirectional and production meters', () => {
        renderForm({ ...defaultMeteringPointForm(), meter_type: 'bidirectional' })
        expect(container.textContent).toContain('pages.meteringPoints.form.behindMeterGeneration')
        expect(container.textContent).toContain('pages.meteringPoints.form.behindMeterGenerationHelp')

        act(() => root.unmount())
        container.remove()
        renderForm({ ...defaultMeteringPointForm(), meter_type: 'production' })
        expect(container.textContent).toContain('pages.meteringPoints.form.behindMeterGeneration')
    })

    it('clears the flag and hides the checkbox when switching to consumption', async () => {
        renderForm({ ...defaultMeteringPointForm(), meter_type: 'bidirectional', has_behind_meter_generation: true })
        // Two switches render on this form ("Active" and "Behind meter
        // generation"); ours is always the last one.
        const behindMeterCheckbox = () => {
            const checkboxes = container.querySelectorAll('input[type="checkbox"]')
            return checkboxes[checkboxes.length - 1] as HTMLInputElement
        }
        expect(behindMeterCheckbox().checked).toBe(true)

        const select = container.querySelector('select') as HTMLSelectElement
        await act(async () => {
            setSelectValue(select, 'consumption')
        })
        expect(container.textContent).not.toContain('pages.meteringPoints.form.behindMeterGeneration')

        // Switching back to a type that allows the flag shows it unchecked —
        // proof the value was actually cleared, not just hidden.
        await act(async () => {
            setSelectValue(select, 'bidirectional')
        })
        expect(behindMeterCheckbox().checked).toBe(false)
    })
})
