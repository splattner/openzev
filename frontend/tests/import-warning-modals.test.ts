import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import i18n from 'i18next'
import { en } from '../src/i18n/locales/en'
import { VseTariffImportModal } from '../src/features/tariffs/VseTariffImportModal'
import { ZevImportModal } from '../src/features/zev/ZevImportModal'
import type { VseTariffImportResult, ZevArchiveImportResult } from '../src/types/api'

const mutations: Array<{ onSuccess: (result: unknown) => void }> = []
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: undefined }),
  useMutation: (options: { onSuccess: (result: unknown) => void }) => {
    mutations.push(options)
    return { isPending: false, mutate: vi.fn() }
  },
}))
const translations = i18n.createInstance()
beforeAll(async () => {
  await translations.init({ lng: 'en', resources: { en: { translation: en } }, interpolation: { escapeValue: false } })
})
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translations.getFixedT('en') }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
  const settings = { date_format_short: 'dd.MM.yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '' }
  return { ...actual, useAppSettings: () => ({ settings, isLoading: false }) }
})

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
beforeEach(() => {
  mutations.length = 0
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

it('retains apply-time warnings under the created VSE tariff', () => {
  act(() => root.render(createElement(VseTariffImportModal, {
    isOpen: true, onClose: vi.fn(), zevId: 'zev', initialUrl: '',
  })))
  const result: VseTariffImportResult = {
    created: [{ name: 'Integrated', category: 'energy', billing_mode: 'energy',
      valid_from: '2026-01-01', valid_to: null, dynamic: true,
      dynamic_source_warnings: ['RAW included components', 'RAW disabled source'],
      dynamic_source_warning_diagnostics: [
        { code: 'components_included', params: { tariff_type: 'energy', components: 'grid' } },
        { code: 'source_disabled', params: { name: 'Integrated' } },
      ] }],
    skipped: [], errors: [],
  }
  act(() => mutations[1].onSuccess(result))
  const row = Array.from(container.querySelectorAll('li')).find((item) => item.textContent?.includes('Integrated'))!
  expect(row.textContent).toContain(translations.t('importDiagnostics.components_included', {
    tariff_type: 'energy', components: translations.t('pages.dynamicSources.types.grid'),
  }))
  expect(row.textContent).toContain(translations.t('importDiagnostics.source_disabled', { name: 'Integrated' }))
  expect(row.textContent).not.toContain('RAW')
})

it('keeps transfer warnings visible until the operator closes the result', () => {
  const onImported = vi.fn()
  act(() => root.render(createElement(ZevImportModal, { isOpen: true, onClose: vi.fn(), onImported })))
  const result: ZevArchiveImportResult = {
    zev_id: 'restored', zev_name: 'Restored', sections: ['zev'], counts: {},
    warnings: ['RAW disabled destination'],
    warning_diagnostics: [{ code: 'source_disabled', params: { name: 'Destination' } }],
  }
  act(() => mutations[1].onSuccess(result))
  expect(container.textContent).toContain(translations.t('importDiagnostics.source_disabled', { name: 'Destination' }))
  expect(container.textContent).not.toContain('RAW')
  expect(container.querySelector('input[type=file]')).toBeNull()
  expect(onImported).not.toHaveBeenCalled()
  const close = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === translations.t('common.close'))!
  act(() => close.click())
  expect(onImported).toHaveBeenCalledWith('restored')
})

it('shows the archive export time in Swiss time, not the browser zone (ADR 0026)', () => {
  const savedTz = process.env.TZ
  process.env.TZ = 'America/New_York'
  try {
    act(() => root.render(createElement(ZevImportModal, { isOpen: true, onClose: vi.fn(), onImported: vi.fn() })))
    act(() => mutations[0].onSuccess({
      format_version: 1, exported_at: '2026-07-15T21:15:00+00:00', source_instance: 'x',
      sections: ['zev'], counts: {}, source_zev: { id: 'z', name: 'Source' },
    }))
    expect(container.textContent).toContain('15.07.2026 23:15')
  } finally {
    process.env.TZ = savedTz
  }
})
