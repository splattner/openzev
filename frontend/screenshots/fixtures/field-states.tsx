import { MantineProvider, Textarea, TextInput } from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { createRoot } from 'react-dom/client'
import { mantineTheme } from '../../src/lib/mantineTheme'

/** Browser-only fixture: exercise real props without adding a product route. */
export function mountFieldStates() {
  const host = document.createElement('div')
  host.id = 'field-state-fixture'
  host.style.cssText = 'position:fixed;inset:0;z-index:2000;overflow:auto;padding:24px;background:var(--white)'
  document.body.appendChild(host)
  createRoot(host).render(
    <MantineProvider theme={mantineTheme}>
      <div className="page-stack">
        <label>
          <span>Native reference</span>
          <input defaultValue="Reference" />
        </label>
        <TextInput label="Neutral field" defaultValue="Value" description="Field help" />
        <TextInput label="Invalid field" defaultValue="Value" error="Invalid value" />
        <TextInput label="Successful field" defaultValue="Value" success="Valid value" />
        <TextInput label="Disabled field" defaultValue="Value" disabled />
        <TextInput label="Field with icons" defaultValue="Value" leftSection="L" rightSection="R" />
        <DatePickerInput label="Invalid date" defaultValue="2026-09-20" error="Invalid date value" />
        <Textarea label="Multiline field" rows={4} defaultValue={'First\nSecond\nThird\nFourth'} />
      </div>
    </MantineProvider>,
  )
}
