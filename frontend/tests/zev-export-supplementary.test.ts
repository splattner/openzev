import { act, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ZevExportModal } from '../src/features/zev/ZevExportModal'
import { DEFAULT_SECTIONS, toggleSection, type TransferSectionName } from '../src/features/zev/transferSections'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/api/zevTransfer', () => ({
    exportZevArchive: vi.fn(),
    fetchTransferSections: vi.fn().mockResolvedValue(undefined),
    readBlobError: vi.fn(),
}))

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const byName = (name: TransferSectionName) => DEFAULT_SECTIONS.find((section) => section.name === name)!

describe('supplementary_data section rules', () => {
    it('needs metering points and participants', () => {
        expect(byName('supplementary_data').requires.sort()).toEqual(['metering_points', 'participants'])
    })

    it('pulls both in when ticked and goes when either is unticked', () => {
        const ticked = toggleSection(DEFAULT_SECTIONS, [], 'supplementary_data')
        expect(ticked).toEqual(['participants', 'metering_points', 'supplementary_data'])
        expect(toggleSection(DEFAULT_SECTIONS, ticked, 'participants')).toEqual([])
        expect(toggleSection(DEFAULT_SECTIONS, ticked, 'metering_points')).toEqual(['participants'])
    })
})

describe('ZevExportModal', () => {
    const open = () => renderWithProviders(
        createElement(ZevExportModal, { isOpen: true, zevId: 'z1', zevName: 'Sonnenhof', onClose: vi.fn() }), cleanups)
    const box = (name: string) =>
        Array.from(document.querySelectorAll<HTMLLabelElement>('label.checkbox-row'))
            .find((label) => label.textContent?.includes(`zevTransfer.sections.${name}`))!
            .querySelector('input')!

    it('leaves the energy data of the participants out until it is asked for', async () => {
        await open()

        expect(box('supplementary_data').checked).toBe(false)
        expect(box('readings').checked).toBe(false)
        expect(box('zev').checked).toBe(true)
        expect(document.body.textContent).not.toContain('zevTransfer.supplementaryNote')
    })

    it('says what the section carries and what it does not once it is ticked', async () => {
        await open()

        await act(async () => { box('supplementary_data').click() })

        expect(box('supplementary_data').checked).toBe(true)
        expect(box('metering_points').checked).toBe(true)
        expect(box('participants').checked).toBe(true)
        expect(document.body.textContent).toContain('zevTransfer.supplementaryNote')
    })
})
