import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo } from 'react'
import { GeoJSON, MapContainer, TileLayer, useMap } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { Building, BuildingFootprint } from '../../types/api'
import { CHART_LOCAL } from '../../lib/chartTokens'

export interface BuildingMapEntry {
    id: string
    name: string
    address: string
    footprint?: BuildingFootprint | null
    participants: string[]
}

interface BuildingMapGroup {
    footprint: BuildingFootprint
    buildings: BuildingMapEntry[]
}

/** One-line address of a building. */
export function buildingMapAddress(building: Building): string {
    return [building.address_line1, building.address_line2, [building.postal_code, building.city].filter(Boolean).join(' ')]
        .filter((part) => part.trim())
        .join(', ')
}

export function toMapEntries(buildings: Building[]): BuildingMapEntry[] {
    return buildings.map((building) => ({
        id: building.id,
        name: building.name,
        address: buildingMapAddress(building),
        footprint: building.building_footprint,
        participants: building.current_participants.map((participant) => participant.display_name),
    }))
}

// Buildings that resolve to the exact same cached footprint (two entries for
// one house) would be drawn twice — group them into one polygon with every
// building in its popup instead.
export function groupBuildingsByFootprint(entries: BuildingMapEntry[]): BuildingMapGroup[] {
    const groups = new Map<string, BuildingMapGroup>()
    for (const entry of entries) {
        if (!entry.footprint) continue
        const key = JSON.stringify(entry.footprint)
        const existing = groups.get(key)
        if (existing) {
            existing.buildings.push(entry)
        } else {
            groups.set(key, { footprint: entry.footprint, buildings: [entry] })
        }
    }
    return [...groups.values()]
}

export function countUnlocated(entries: BuildingMapEntry[]): number {
    return entries.filter((entry) => !entry.footprint).length
}

const SWITZERLAND_CENTER: [number, number] = [46.8182, 8.2275]
const DEFAULT_ZOOM = 7
function FitToGroups({ groups }: { groups: BuildingMapGroup[] }) {
    const map = useMap()

    useEffect(() => {
        if (groups.length === 0) return
        const bounds = L.latLngBounds([])
        for (const group of groups) {
            bounds.extend(L.geoJSON(group.footprint).getBounds())
        }
        map.fitBounds(bounds, { padding: [24, 24], maxZoom: 18 })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [map, JSON.stringify(groups)])

    return null
}

// Builds the popup content with safe DOM APIs (textContent, never innerHTML)
// since building and participant names are user-entered data.
function bindGroupPopup(group: BuildingMapGroup, labels: { participants: string; none: string }) {
    return (_feature: unknown, layer: L.Layer) => {
        const container = document.createElement('div')
        for (const building of group.buildings) {
            const block = document.createElement('div')
            const heading = document.createElement('strong')
            heading.textContent = building.name
            const addressLine = document.createElement('div')
            addressLine.textContent = building.address
            const people = document.createElement('div')
            people.textContent = building.participants.length > 0
                ? `${labels.participants} ${building.participants.join(', ')}`
                : labels.none
            block.append(heading, addressLine, people)
            container.append(block)
        }
        layer.bindPopup(container)
    }
}

interface BuildingsMapProps {
    buildings: Building[]
}

/** The participants page map (ADR 0012, amended): where the meters are, not where invoices go. */
export function BuildingsMap({ buildings }: BuildingsMapProps) {
    const { t } = useTranslation()
    const entries = useMemo(() => toMapEntries(buildings), [buildings])
    const groups = useMemo(() => groupBuildingsByFootprint(entries), [entries])
    const missing = useMemo(() => countUnlocated(entries), [entries])
    const labels = { participants: t('pages.participants.map.popupParticipants'), none: t('pages.participants.map.popupNoParticipants') }

    if (groups.length === 0) {
        return <p className="muted">{t('pages.participants.map.empty')}</p>
    }

    return (
        <div>
            <div style={{ height: '350px', borderRadius: '0.75rem', overflow: 'hidden' }}>
                <MapContainer
                    center={SWITZERLAND_CENTER}
                    zoom={DEFAULT_ZOOM}
                    scrollWheelZoom={false}
                    style={{ height: '100%', width: '100%' }}
                >
                    <TileLayer
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                    />
                    <FitToGroups groups={groups} />
                    {groups.map((group) => (
                        <GeoJSON
                            key={group.buildings.map((building) => building.id).join('-')}
                            data={group.footprint}
                            style={{ color: CHART_LOCAL, weight: 2, fillOpacity: 0.25 }}
                            onEachFeature={bindGroupPopup(group, labels)}
                        />
                    ))}
                </MapContainer>
            </div>
            {missing > 0 && (
                <p className="muted" style={{ fontSize: '0.82rem', marginTop: '0.4rem' }}>
                    {t('pages.participants.map.notShown', { count: missing })}
                </p>
            )}
        </div>
    )
}
