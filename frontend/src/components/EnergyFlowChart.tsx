import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface EnergyFlowChartProps {
    totals: {
        produced_kwh: number
        consumed_kwh: number
        imported_kwh: number
        exported_kwh: number
    }
    participantStats: Array<{
        participant_id: string
        participant_name: string
        total_consumed_kwh: number
        total_produced_kwh: number
        from_zev_kwh: number
        from_grid_kwh: number
    }>
    /** When set, show this participant individually and aggregate all others into "Others" */
    highlightParticipantId?: string
}

const PRODUCER_COLORS = ['#16a34a', '#22c55e', '#15803d', '#059669', '#4ade80', '#34d399']
const CONSUMER_COLORS = ['#2563eb', '#3b82f6', '#1d4ed8', '#6366f1', '#60a5fa', '#818cf8', '#93c5fd']
const TOTAL_PROD_COLOR = '#16a34a'
const LOCAL_CONS_COLOR = '#0ea5e9'
const GRID_IMPORT_COLOR = '#f59e0b'
const GRID_EXPORT_COLOR = '#8b5cf6'

const VIEW_W = 960
const PAD_TOP = 28
const PAD_BOTTOM = 44
const PAD_LEFT = 140
const PAD_RIGHT = 140
const BAR_W = 14
const MIN_NODE_H = 6
const OUTER_GAP = 10
const INNER_GAP = 56

const COL_USABLE = VIEW_W - PAD_LEFT - PAD_RIGHT - BAR_W
const COL_X = [
    PAD_LEFT,
    Math.round(PAD_LEFT + COL_USABLE / 4),
    Math.round(PAD_LEFT + (COL_USABLE * 2) / 4),
    Math.round(PAD_LEFT + (COL_USABLE * 3) / 4),
    PAD_LEFT + COL_USABLE,
]

interface SNode {
    id: string
    label: string
    value: number
    color: string
    col: number
    y: number
    h: number
    pct?: string
}

interface SLink {
    id: string
    sourceId: string
    targetId: string
    value: number
    color: string
    sy: number
    ty: number
    th: number
    sx: number
    tx: number
}

function sankeyPath(x1: number, sy: number, x2: number, ty: number, thickness: number): string {
    const mx = (x1 + x2) / 2
    return [
        `M${x1},${sy}`,
        `C${mx},${sy} ${mx},${ty} ${x2},${ty}`,
        `L${x2},${ty + thickness}`,
        `C${mx},${ty + thickness} ${mx},${sy + thickness} ${x1},${sy + thickness}`,
        'Z',
    ].join(' ')
}

const OTHERS_COLOR = '#94a3b8'

export function EnergyFlowChart({ totals, participantStats, highlightParticipantId }: EnergyFlowChartProps) {
    const { t } = useTranslation()
    const [hoverNode, setHoverNode] = useState<string | null>(null)
    const [hoverLink, setHoverLink] = useState<string | null>(null)

    const data = useMemo(() => {
        const totalProduced = totals.produced_kwh
        const producers = participantStats.filter(p => p.total_produced_kwh > 0)
        const allConsumers = participantStats.filter(p => p.total_consumed_kwh > 0)

        // When highlighting a specific participant, aggregate others
        let consumers: typeof allConsumers
        if (highlightParticipantId) {
            const highlighted = allConsumers.find(c => c.participant_id === highlightParticipantId)
            const others = allConsumers.filter(c => c.participant_id !== highlightParticipantId)
            consumers = []
            if (highlighted) consumers.push(highlighted)
            if (others.length > 0) {
                consumers.push({
                    participant_id: '__others__',
                    participant_name: t('pages.dashboard.energyFlow.others'),
                    total_consumed_kwh: others.reduce((s, p) => s + p.total_consumed_kwh, 0),
                    total_produced_kwh: others.reduce((s, p) => s + p.total_produced_kwh, 0),
                    from_zev_kwh: others.reduce((s, p) => s + p.from_zev_kwh, 0),
                    from_grid_kwh: others.reduce((s, p) => s + p.from_grid_kwh, 0),
                })
            }
        } else {
            consumers = allConsumers
        }

        // Derive balanced values from participant-level data so flows match node sizes
        const sumFromZev = consumers.reduce((s, p) => s + p.from_zev_kwh, 0)
        const sumFromGrid = consumers.reduce((s, p) => s + p.from_grid_kwh, 0)
        const localCons = sumFromZev > 0 ? sumFromZev : Math.max(0, totalProduced - totals.exported_kwh)
        const gridImport = sumFromGrid > 0 ? sumFromGrid : totals.imported_kwh
        const gridExport = Math.max(0, totalProduced - localCons)

        if (totalProduced <= 0 && gridImport <= 0) return null
        if (consumers.length === 0 && gridExport <= 0) return null

        // --- Col 0: Individual producers ---
        type NDef = { id: string; label: string; value: number; color: string; col: number; pct?: string }
        const col0: NDef[] = []
        const attributedProd = producers.reduce((s, p) => s + p.total_produced_kwh, 0)

        if (totalProduced > 0) {
            if (attributedProd > 0) {
                const scaleFactor = attributedProd > totalProduced ? totalProduced / attributedProd : 1
                producers.forEach((p, i) => {
                    col0.push({
                        id: `prod-${p.participant_id}`,
                        label: p.participant_name || `Producer ${i + 1}`,
                        value: p.total_produced_kwh * scaleFactor,
                        color: PRODUCER_COLORS[i % PRODUCER_COLORS.length],
                        col: 0,
                    })
                })
                const remainder = totalProduced - attributedProd * scaleFactor
                if (remainder > 0.01) {
                    col0.push({
                        id: 'prod-other',
                        label: t('pages.dashboard.energyFlow.localProduction'),
                        value: remainder,
                        color: PRODUCER_COLORS[producers.length % PRODUCER_COLORS.length],
                        col: 0,
                    })
                }
            } else {
                col0.push({
                    id: 'prod-local',
                    label: t('pages.dashboard.energyFlow.localProduction'),
                    value: totalProduced,
                    color: TOTAL_PROD_COLOR,
                    col: 0,
                })
            }
        }

        // --- Col 1: Total Local Production ---
        const col1: NDef[] = []
        if (totalProduced > 0) {
            col1.push({
                id: 'total-prod',
                label: t('pages.dashboard.energyFlow.totalLocalProduction'),
                value: totalProduced,
                color: TOTAL_PROD_COLOR,
                col: 1,
            })
        }

        // --- Col 2: Local Consumption + Grid Export ---
        const selfConsumptionPct = totalProduced > 0 ? ((Math.max(0, totalProduced - gridExport)) / totalProduced * 100) : 0
        const exportPct = totalProduced > 0 ? (gridExport / totalProduced * 100) : 0
        const col2: NDef[] = []
        if (localCons > 0) {
            col2.push({
                id: 'local-cons',
                label: t('pages.dashboard.energyFlow.localConsumption'),
                value: localCons,
                color: LOCAL_CONS_COLOR,
                col: 2,
                pct: `${selfConsumptionPct.toFixed(1)}%`,
            })
        }
        if (gridExport > 0) {
            col2.push({
                id: 'grid-export',
                label: t('pages.dashboard.energyFlow.gridExport'),
                value: gridExport,
                color: GRID_EXPORT_COLOR,
                col: 2,
                pct: `${exportPct.toFixed(1)}%`,
            })
        }

        // --- Col 3: Grid Import ---
        const col3: NDef[] = []
        if (gridImport > 0) {
            col3.push({
                id: 'grid-import',
                label: t('pages.dashboard.energyFlow.gridImport'),
                value: gridImport,
                color: GRID_IMPORT_COLOR,
                col: 3,
            })
        }

        // --- Col 4: Individual consumers (or highlighted + Others) ---
        const col4: NDef[] = consumers.map((p, i) => ({
            id: `cons-${p.participant_id}`,
            label: p.participant_name || `Consumer ${i + 1}`,
            value: p.total_consumed_kwh,
            color: p.participant_id === '__others__' ? OTHERS_COLOR : CONSUMER_COLORS[i % CONSUMER_COLORS.length],
            col: 4,
        }))

        const allCols = [col0, col1, col2, col3, col4]
        if (allCols.every(c => c.length === 0)) return null

        // --- Compute unified scale so flow thickness is consistent ---
        const maxNodes = Math.max(...allCols.map(c => c.length))
        const viewH = Math.max(280, Math.min(550, maxNodes * 56 + PAD_TOP + PAD_BOTTOM))
        const usableH = viewH - PAD_TOP - PAD_BOTTOM

        let scale = Infinity
        for (const col of allCols) {
            if (col.length === 0) continue
            const totalVal = col.reduce((s, n) => s + n.value, 0)
            if (totalVal <= 0) continue
            const isInner = col[0].col >= 1 && col[0].col <= 3
            const gap = isInner ? INNER_GAP : OUTER_GAP
            const availH = usableH - (col.length - 1) * gap
            if (availH > 0) scale = Math.min(scale, availH / totalVal)
        }
        if (!isFinite(scale) || scale <= 0) return null

        // --- Position nodes (vertically centered per column) ---
        function positionCol(defs: NDef[]): SNode[] {
            if (defs.length === 0) return []
            const isInner = defs[0].col >= 1 && defs[0].col <= 3
            const gap = isInner ? INNER_GAP : OUTER_GAP
            const totalH = defs.reduce((s, n) => s + Math.max(MIN_NODE_H, n.value * scale), 0) + (defs.length - 1) * gap
            let y = PAD_TOP + (usableH - totalH) / 2
            return defs.map(def => {
                const h = Math.max(MIN_NODE_H, def.value * scale)
                const node: SNode = { ...def, y, h }
                y += h + gap
                return node
            })
        }

        const positioned = allCols.map(positionCol)
        const nodes = positioned.flat()
        const nMap: Record<string, SNode> = {}
        nodes.forEach(n => { nMap[n.id] = n })

        // --- Build links ---
        type RawLink = { id: string; sourceId: string; targetId: string; value: number; color: string }
        const rawLinks: RawLink[] = []

        // Col 0 -> Col 1: producers -> total production
        if (nMap['total-prod']) {
            for (const n of positioned[0]) {
                rawLinks.push({ id: `${n.id}->total-prod`, sourceId: n.id, targetId: 'total-prod', value: n.value, color: n.color })
            }
        }

        // Col 1 -> Col 2: total production -> local consumption + grid export
        if (nMap['total-prod'] && nMap['local-cons']) {
            rawLinks.push({ id: 'total-prod->local-cons', sourceId: 'total-prod', targetId: 'local-cons', value: localCons, color: LOCAL_CONS_COLOR })
        }
        if (nMap['total-prod'] && nMap['grid-export']) {
            rawLinks.push({ id: 'total-prod->grid-export', sourceId: 'total-prod', targetId: 'grid-export', value: gridExport, color: GRID_EXPORT_COLOR })
        }

        // Col 2 -> Col 4: local consumption -> consumers (from_zev share)
        if (nMap['local-cons']) {
            for (const c of consumers) {
                if (c.from_zev_kwh < 0.01) continue
                const tid = `cons-${c.participant_id}`
                if (!nMap[tid]) continue
                rawLinks.push({ id: `local-cons->${tid}`, sourceId: 'local-cons', targetId: tid, value: c.from_zev_kwh, color: LOCAL_CONS_COLOR })
            }
        }

        // Col 3 -> Col 4: grid import -> consumers (from_grid share)
        if (nMap['grid-import']) {
            for (const c of consumers) {
                if (c.from_grid_kwh < 0.01) continue
                const tid = `cons-${c.participant_id}`
                if (!nMap[tid]) continue
                rawLinks.push({ id: `grid-import->${tid}`, sourceId: 'grid-import', targetId: tid, value: c.from_grid_kwh, color: GRID_IMPORT_COLOR })
            }
        }

        // --- Position links (compute y offsets per node port) ---
        const srcOut: Record<string, number> = {}
        const tgtIn: Record<string, number> = {}
        nodes.forEach(n => { srcOut[n.id] = n.y; tgtIn[n.id] = n.y })

        const links: SLink[] = rawLinks.map(lk => {
            const src = nMap[lk.sourceId]
            const tgt = nMap[lk.targetId]
            const th = Math.max(1, lk.value * scale)
            const sy = srcOut[lk.sourceId]
            const ty = tgtIn[lk.targetId]
            srcOut[lk.sourceId] += th
            tgtIn[lk.targetId] += th
            return { ...lk, sy, ty, th, sx: COL_X[src.col] + BAR_W, tx: COL_X[tgt.col] }
        })

        return { nodes, links, viewH }
    }, [totals, participantStats, highlightParticipantId, t])

    if (!data) return <p className="muted">{t('pages.dashboard.noData')}</p>

    const { nodes, links, viewH } = data
    const anyHover = hoverNode !== null || hoverLink !== null

    const isLinkHit = (lk: SLink) => {
        if (!anyHover) return false
        if (hoverLink === lk.id) return true
        if (hoverNode) return lk.sourceId === hoverNode || lk.targetId === hoverNode
        return false
    }

    const isNodeActive = (id: string) => {
        if (!anyHover) return true
        if (hoverNode === id) return true
        if (hoverLink) {
            const lk = links.find(l => l.id === hoverLink)
            return lk?.sourceId === id || lk?.targetId === id
        }
        return links.some(l =>
            (l.sourceId === hoverNode || l.targetId === hoverNode) &&
            (l.sourceId === id || l.targetId === id),
        )
    }

    return (
        <svg
            viewBox={`0 0 ${VIEW_W} ${viewH}`}
            style={{ width: '100%', height: 'auto', display: 'block' }}
            onMouseLeave={() => { setHoverNode(null); setHoverLink(null) }}
        >
            {/* Flow ribbons */}
            {links.map(lk => {
                const hit = isLinkHit(lk)
                const dim = anyHover && !hit
                const src = nodes.find(n => n.id === lk.sourceId)!
                const tgt = nodes.find(n => n.id === lk.targetId)!
                const midX = (lk.sx + lk.tx) / 2
                const midY = (lk.sy + lk.ty + lk.th) / 2
                return (
                    <g key={lk.id}>
                        <path
                            d={sankeyPath(lk.sx, lk.sy, lk.tx, lk.ty, lk.th)}
                            fill={lk.color}
                            fillOpacity={dim ? 0.06 : hit ? 0.4 : 0.2}
                            stroke={lk.color}
                            strokeOpacity={dim ? 0.08 : hit ? 0.55 : 0.25}
                            strokeWidth={0.5}
                            style={{ transition: 'fill-opacity 200ms, stroke-opacity 200ms', cursor: 'pointer' }}
                            onMouseEnter={() => setHoverLink(lk.id)}
                            onMouseLeave={() => setHoverLink(null)}
                        >
                            <title>{`${src.label} → ${tgt.label}: ${lk.value.toFixed(1)} kWh`}</title>
                        </path>
                        {lk.th >= 10 && hit && (
                            <text
                                x={midX}
                                y={midY}
                                textAnchor="middle"
                                dominantBaseline="central"
                                fontSize={9}
                                fill="#374151"
                                fillOpacity={0.85}
                                style={{ pointerEvents: 'none' }}
                            >
                                {lk.value.toFixed(1)} kWh
                            </text>
                        )}
                    </g>
                )
            })}

            {/* Nodes (bars + labels), rendered after ribbons so they appear on top */}
            {nodes.map(n => {
                const active = isNodeActive(n.id)
                const isLeft = n.col === 0
                const isRight = n.col === 4
                const isMid = n.col >= 1 && n.col <= 3
                const x = COL_X[n.col]

                return (
                    <g
                        key={n.id}
                        style={{ cursor: 'pointer', opacity: active ? 1 : 0.3, transition: 'opacity 200ms' }}
                        onMouseEnter={() => setHoverNode(n.id)}
                        onMouseLeave={() => setHoverNode(null)}
                    >
                        <rect x={x} y={n.y} width={BAR_W} height={n.h} fill={n.color} rx={2} />

                        {isLeft && (
                            <>
                                <text x={x - 8} y={n.y + n.h / 2 - 6} textAnchor="end" dominantBaseline="central" fontSize={11} fill="#374151">{n.label}</text>
                                <text x={x - 8} y={n.y + n.h / 2 + 7} textAnchor="end" dominantBaseline="central" fontSize={10} fill="#9ca3af">{n.value.toFixed(1)} kWh</text>
                            </>
                        )}

                        {isRight && (
                            <>
                                <text x={x + BAR_W + 8} y={n.y + n.h / 2 - 6} textAnchor="start" dominantBaseline="central" fontSize={11} fill="#374151">{n.label}</text>
                                <text x={x + BAR_W + 8} y={n.y + n.h / 2 + 7} textAnchor="start" dominantBaseline="central" fontSize={10} fill="#9ca3af">{n.value.toFixed(1)} kWh</text>
                            </>
                        )}

                        {isMid && (
                            <>
                                <text x={x + BAR_W / 2} y={n.y + n.h + 14} textAnchor="middle" fontSize={10} fill="#374151">{n.label}</text>
                                <text x={x + BAR_W / 2} y={n.y + n.h + 26} textAnchor="middle" fontSize={9} fill="#9ca3af">{n.value.toFixed(1)} kWh</text>
                                {n.pct && (
                                    <text x={x + BAR_W / 2} y={n.y + n.h + 38} textAnchor="middle" fontSize={10} fontWeight={600} fill={n.color}>{n.pct}</text>
                                )}
                            </>
                        )}


                    </g>
                )
            })}
        </svg>
    )
}
