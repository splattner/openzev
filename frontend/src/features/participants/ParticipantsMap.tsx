import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo } from 'react'
import { GeoJSON, MapContainer, TileLayer, useMap } from 'react-leaflet'
import { useTranslation } from 'react-i18next'
import type { ParticipantBuildingFootprint } from '../../types/api'
import { FLOW_LOCAL_CONS } from '../../lib/chartTokens'

export interface ParticipantMapEntry {
    id: string
    displayName: string
    address: string
    buildingFootprint?: ParticipantBuildingFootprint | null
}

interface ParticipantMapGroup {
    footprint: ParticipantBuildingFootprint
    participants: Array<{ id: string; displayName: string; address: string }>
}

// Two participants at the same building resolve to the exact same cached
// footprint — drawing it twice would be pixel-redundant, so group them into
// one polygon with every name in its popup instead.
export function groupParticipantsByBuilding(entries: ParticipantMapEntry[]): ParticipantMapGroup[] {
    const groups = new Map<string, ParticipantMapGroup>()
    for (const entry of entries) {
        if (!entry.buildingFootprint) continue
        const key = JSON.stringify(entry.buildingFootprint)
        const participant = { id: entry.id, displayName: entry.displayName, address: entry.address }
        const existing = groups.get(key)
        if (existing) {
            existing.participants.push(participant)
        } else {
            groups.set(key, { footprint: entry.buildingFootprint, participants: [participant] })
        }
    }
    return [...groups.values()]
}

export function countMissingBbox(entries: ParticipantMapEntry[]): number {
    return entries.filter((entry) => !entry.buildingFootprint).length
}

const SWITZERLAND_CENTER: [number, number] = [46.8182, 8.2275]
const DEFAULT_ZOOM = 7
function FitToGroups({ groups }: { groups: ParticipantMapGroup[] }) {
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
// since participant names/addresses are user-entered data.
function bindGroupPopup(group: ParticipantMapGroup) {
    return (_feature: unknown, layer: L.Layer) => {
        const container = document.createElement('div')
        const heading = document.createElement('strong')
        heading.textContent = group.participants.map((participant) => participant.displayName).join(', ')
        const addressLine = document.createElement('div')
        addressLine.textContent = group.participants[0].address
        container.append(heading, addressLine)
        layer.bindPopup(container)
    }
}

interface ParticipantsMapProps {
    participants: ParticipantMapEntry[]
}

export function ParticipantsMap({ participants }: ParticipantsMapProps) {
    const { t } = useTranslation()
    const groups = useMemo(() => groupParticipantsByBuilding(participants), [participants])
    const missing = useMemo(() => countMissingBbox(participants), [participants])

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
                            key={group.participants.map((participant) => participant.id).join('-')}
                            data={group.footprint}
                            style={{ color: FLOW_LOCAL_CONS, weight: 2, fillOpacity: 0.25 }}
                            onEachFeature={bindGroupPopup(group)}
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
