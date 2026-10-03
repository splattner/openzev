import { createRoot } from 'react-dom/client'
import { PageHeader } from '../../src/components/PageHeader'
import { StatCard } from '../../src/components/StatCard'
import { Toolbar } from '../../src/components/Toolbar'

export function mountPageLayout() {
  const host = document.createElement('div')
  host.id = 'page-layout-fixture'
  host.style.cssText = 'position:fixed;inset:20px auto auto 20px;width:320px;z-index:2000;background:var(--white)'
  document.body.appendChild(host)
  createRoot(host).render(
    <div className="page-stack">
      <PageHeader
        eyebrow="WasserversorgungsgemeinschaftSonnenhofOhneTrennzeichen"
        title="WasserversorgungsabrechnungsübersichtOhneTrennzeichen"
        description="Teilnehmerzuordnungen und Abrechnungszeiträume verwalten."
        actions={<button type="button" className="button">TeilnehmerzuordnungBearbeitenOhneTrennzeichen</button>}
      />
      <Toolbar actions={<button type="button" className="button">TeilnehmerzuordnungBearbeitenOhneTrennzeichen</button>}>
        <span>Teilnehmerzuordnungen und Abrechnungszeiträume</span>
      </Toolbar>
      <section className="stat-grid stat-grid--wide" style={{ width: 200 }}>
        <StatCard label="Gesamter Stromverbrauch aus Netz und Gemeinschaft" value="1’234’567.9 kWh" />
        <StatCard label="Abrechnungsbetrag" value="CHF 1’234’567.89" />
        <StatCard label="Eigenverbrauchsanteil" value="37.5 %" />
      </section>
    </div>,
  )
}
