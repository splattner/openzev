import { MantineProvider } from '@mantine/core'
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ParticipantCardsSection } from '../src/features/participants/ParticipantCardsSection'
import i18n from '../src/i18n'

type Props = ComponentProps<typeof ParticipantCardsSection>
type Card = Props['participantCards'][number]

function card(id: string, allocationWeight: string, validityState: Card['validityState'] = 'current'): Card {
    return {
        participant: {
            id, zev: 'zev-1', user: null, first_name: id, last_name: 'Example', email: '',
            valid_from: '2026-01-01', allocation_weight: allocationWeight,
        },
        validityState, displayName: id, address: '', issues: [], roles: [],
    }
}

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
beforeEach(async () => {
    await i18n.changeLanguage('en')
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })

function render(participantCards: Card[], filteredParticipants = participantCards, overrides: Partial<Props> = {}) {
    const props: Props = {
        participantCards, filteredParticipants,
        settings: { date_format_short: 'yyyy-MM-dd', date_format_long: 'yyyy-MM-dd', date_time_format: 'yyyy-MM-dd HH:mm', updated_at: '' },
        onOpenCreateModal: vi.fn(), onClearFilters: vi.fn(), onStartEdit: vi.fn(),
        onDownloadContract: vi.fn(), onSendOnboardingLink: vi.fn(), onCopyOnboardingLink: vi.fn(),
        onRevokeOnboardingLink: vi.fn(), onConfirmDelete: vi.fn(), onLinkAccount: vi.fn(), onUnlinkAccount: vi.fn(),
        canLinkAccount: false, canUnlinkAccount: false, accountActionPending: false,
        onboardingLinkPending: false, deletePendingOrDialogLoading: false, readOnly: true,
        ...overrides,
    }
    act(() => root.render(createElement(MantineProvider, null, createElement(MemoryRouter, null, createElement(ParticipantCardsSection, props)))))
}

function weightDisplay(id: string) {
    const element = container.querySelector(`#participant-row-${id} [data-testid="participant-weight"]`)
    if (!element) throw new Error(`Missing weight display for ${id}`)
    return element
}

/** The line under the share: weight / total for a current row, the weight alone otherwise. */
function weightLine(id: string) {
    return container.querySelector(`#participant-row-${id} .participant-row-weight`)?.textContent
}

describe('Participant allocation shares', () => {
    it('excludes ended and upcoming participations from the current total', () => {
        render([
            card('anna', '1.0000'), card('ben', '2.0000'), card('garage', '0.2500'),
            card('maria', '2.0000', 'ended'), card('joiner', '4.0000', 'upcoming'),
        ])
        expect(weightDisplay('anna').textContent).toBe('30.77 %')
        expect(weightDisplay('ben').textContent).toBe('61.54 %')
        expect(weightDisplay('garage').textContent).toBe('7.69 %')
        expect(weightDisplay('maria').textContent).toBe('–')
        expect(weightDisplay('joiner').textContent).toBe('–')
        expect(weightLine('anna')).toBe('1 / 3.25')
        expect(weightLine('garage')).toBe('0.25 / 3.25')
        expect(weightLine('maria')).toBe('2')
        expect(weightLine('joiner')).toBe('4')
        expect(weightDisplay('anna').getAttribute('title')).toBe('30.77 % — 1 of 3.25 weights')
        expect(weightDisplay('garage').getAttribute('title')).toBe('7.69 % — 0.25 of 3.25 weights')
        expect(weightDisplay('maria').getAttribute('title')).toBe(i18n.t('pages.participants.weightShareUnavailableHint'))
        expect(weightDisplay('joiner').getAttribute('title')).toBe(i18n.t('pages.participants.weightShareUnavailableHint'))
    })

    it('uses the full current total when only a subset of cards is visible', () => {
        const cards = [card('anna', '1'), card('ben', '2'), card('maria', '2', 'ended')]
        render(cards)
        const before = weightDisplay('anna').textContent
        render(cards, [cards[0]])
        expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
        expect(weightDisplay('anna').textContent).toBe(before)
        expect(before).toBe('33.33 %')
    })

    it('shows no percentage when nobody is current', () => {
        render([card('maria', '2', 'ended'), card('joiner', '1', 'upcoming')])
        expect(weightDisplay('maria').textContent).toBe('–')
        expect(weightDisplay('joiner').textContent).toBe('–')
        expect(container.querySelector('tbody')!.textContent).not.toContain('%')
    })

    it('preserves four-decimal weight precision while trimming trailing zeros', () => {
        render([card('tiny', '0.0001'), card('other', '0.2499')])
        expect(weightLine('tiny')).toBe('0.0001 / 0.25')
        expect(weightDisplay('tiny').getAttribute('title')).toBe('0.04 % — 0.0001 of 0.25 weights')
        expect(weightDisplay('other').getAttribute('title')).toBe('99.96 % — 0.2499 of 0.25 weights')
    })

    it('does not require a personal meter to count a current participation', () => {
        const withoutMeter = card('without-meter', '1')
        withoutMeter.participant.has_metering_point_assignment = false
        render([withoutMeter])
        expect(weightDisplay('without-meter').textContent).toBe('100 %')
    })
})

describe('Participant rows', () => {
    it('opens the participant from its name for a writer only', () => {
        const onStartEdit = vi.fn()
        const anna = card('anna', '1')
        render([anna], [anna], { readOnly: false, onStartEdit })
        act(() => container.querySelector<HTMLButtonElement>('.participant-name-button')!.click())
        expect(onStartEdit).toHaveBeenCalledWith(anna.participant)
        render([anna], [anna], { onStartEdit })
        expect(container.querySelector('.participant-name-button')).toBeNull()
    })

    it('makes each missing detail a fix for a writer, with one focusable control per issue', () => {
        const onStartEdit = vi.fn()
        const anna = { ...card('anna', '1'), issues: ['noEmail' as const, 'noMeteringPoint' as const] }
        render([anna], [anna], { readOnly: false, onStartEdit })
        const texts = [...container.querySelectorAll<HTMLElement>('.invoice-row-issues .participant-fix')]
        expect(texts.map((element) => element.tagName)).toEqual(['BUTTON', 'A'])
        expect(texts[1].getAttribute('href')).toBe('/metering/points')
        act(() => texts[0].click())
        expect(onStartEdit).toHaveBeenCalledWith(anna.participant)
        const icons = [...container.querySelectorAll<HTMLElement>('.participant-fix--icon')]
        expect(icons.map((element) => element.tagName)).toEqual(['BUTTON', 'A'])
        expect(icons.every((element) => element.tabIndex === -1 && element.getAttribute('aria-hidden') === 'true')).toBe(true)
    })

    it('shows a viewer the missing details without any control', () => {
        const anna = { ...card('anna', '1'), issues: ['noEmail' as const, 'noMeteringPoint' as const] }
        render([anna], [anna])
        expect(container.querySelectorAll('.participant-rows :is(a, button).participant-fix')).toHaveLength(0)
        expect([...container.querySelectorAll('.invoice-row-issues .participant-fix')].map((element) => element.textContent))
            .toEqual([i18n.t('pages.participants.warnings.noEmail'), i18n.t('pages.participants.warnings.noMeteringPoint')])
    })

    it.each([
        ['not_sent', 'open', 'Not invited'],
        ['sent', 'open', 'Invited, valid until 2026-12-31'],
        ['active', 'done', 'Invitation link used'],
        ['expired', 'open', 'Invitation expired on 2026-12-31'],
        ['revoked', 'open', 'Invitation revoked, e.g. after a password was set'],
    ] as const)('marks an invitation that is %s as %s', (status, state, label) => {
        const anna = card('anna', '1')
        anna.participant.onboarding_status = status
        anna.participant.onboarding_link_expires_at = status === 'revoked' ? null : '2026-12-31T12:00:00Z'
        anna.participant.account_username = 'anna'
        render([anna])
        const step = container.querySelector('[data-step="invitation"]')!
        expect(step.getAttribute('data-state')).toBe(state)
        expect(step.getAttribute('title')).toBe(label)
    })

    it('offers the ended participants when nobody current or upcoming is left', () => {
        const onShowEnded = vi.fn()
        render([card('maria', '2', 'ended')], [], { onShowEnded })
        const button = [...container.querySelectorAll('button')].find((element) => element.textContent === i18n.t('pages.participants.noCurrent.showEnded'))
        act(() => button!.click())
        expect(onShowEnded).toHaveBeenCalled()
    })
})
