import MockAdapter from 'axios-mock-adapter'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === 'pages.dynamicSources.versions.v2_0_0') return 'v2.0.0'
      return values?.version ? `${key}:${values.version}` : key
    },
  }),
}))

import { DynamicSourceFormModal } from '../src/features/tariffs/DynamicSourceFormModal'
import { api } from '../src/lib/api/client'
import { ToastProvider } from '../src/lib/toast'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function setInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('DynamicSourceFormModal discovery wizard', () => {
  let apiMock: MockAdapter
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    apiMock = new MockAdapter(api)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    act(() => {
      root.render(createElement(
        QueryClientProvider,
        { client },
        createElement(ToastProvider, null, createElement(DynamicSourceFormModal, {
          isOpen: true,
          onClose: () => undefined,
        })),
      ))
    })
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    apiMock.restore()
  })

  it('asks for name and URL first, then renders discovered components', async () => {
    expect(container.textContent).toContain('pages.dynamicSources.discovery.step')
    const versionOptions = Array.from(container.querySelectorAll('option')).map((option) => option.value)
    expect(versionOptions).toEqual(['auto', 'v1_0_5', 'v2_0_0'])
    expect(container.textContent).not.toContain('Groupe E')
    expect(container.textContent).not.toContain('BKW')

    apiMock.onPost('/tariffs/dynamic-sources/discover/').reply(200, {
      api_version: 'v2_0_0',
      version_detected: true,
      components_discovered: true,
      components: [
        { tariff_type: 'grid', tariff_name: 'standard', aggregated_tariff_types: [] },
        { tariff_type: 'feed_in', tariff_name: 'solar', aggregated_tariff_types: [] },
      ],
    })
    const inputs = container.querySelectorAll<HTMLInputElement>('input')
    await act(async () => {
      setInput(inputs[0], 'Example prices')
      setInput(inputs[1], 'https://prices.example.test/tariffs')
      container.querySelector<HTMLFormElement>('form')!.requestSubmit()
    })

    for (let attempt = 0; attempt < 20 && !container.textContent?.includes('standard'); attempt += 1) {
      await act(async () => new Promise((resolve) => setTimeout(resolve, 10)))
    }
    expect(container.textContent).toContain('pages.dynamicSources.discovery.detected:v2.0.0')
    expect(container.textContent).toContain('standard')
    expect(container.textContent).toContain('solar')
  })
})
