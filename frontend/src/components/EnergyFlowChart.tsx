import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CHART_GRID, CHART_INK, CHART_MUTED, CONS_COLORS, FLOW_GRID_EXP, FLOW_LOCAL_CONS, OTHERS_COLOR, PROD_COLORS } from '../lib/chartTokens'
import { formatKwh, formatPercent } from '../lib/numbers'

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

const VIEW_W = 960
const PAD_TOP = 28
const PAD_BOTTOM = 44
const BAR_W = 14
const MIN_NODE_H = 6
const OUTER_GAP = 10
const INNER_GAP = 56

// Side gutters hold the participant labels; they grow with the longest label
// up to MAX_SIDE_PAD, beyond which names wrap onto a second line.
const MIN_SIDE_PAD = 140
const MAX_SIDE_PAD = 210
const LABEL_GAP = 8
const LABEL_FONT = 11
const LABEL_LINE_H = 13
const LABEL_MAX_LINES = 2
// Rough average glyph width for the UI sans font; errs on the wide side.
const CHAR_W = LABEL_FONT * 0.6

function textWidth(text: string): number {
    return text.length * CHAR_W
}

function sidePad(labels: string[]): number {
    const widest = labels.reduce((w, l) => Math.max(w, textWidth(l)), 0)
    return Math.round(Math.min(MAX_SIDE_PAD, Math.max(MIN_SIDE_PAD, widest + LABEL_GAP + 6)))
}

/** Greedy word wrap into at most LABEL_MAX_LINES lines; overflow ends in an ellipsis. */
function wrapLabel(label: string, maxWidth: number): string[] {
    const maxChars = Math.max(4, Math.floor(maxWidth / CHAR_W))
    const words = label.trim().split(/\s+/).flatMap(w => {
        const parts: string[] = []
        for (let i = 0; i < w.length; i += maxChars) parts.push(w.slice(i, i + maxChars))
        return parts
    })
    const lines: string[] = []
    let current = ''
    for (const w of words) {
        const next = current ? `${current} ${w}` : w
        if (next.length <= maxChars) {
            current = next
        } else {
            if (current) lines.push(current)
            current = w
        }
    }
    if (current) lines.push(current)
    if (lines.length <= LABEL_MAX_LINES) return lines
    const kept = lines.slice(0, LABEL_MAX_LINES)
    const last = kept[LABEL_MAX_LINES - 1]
    kept[LABEL_MAX_LINES - 1] = `${last.slice(0, maxChars - 1).trimEnd()}…`
    return kept
}

interface SNode {
    id: string
    label: string
    value: number
    color: string
    col: number
    y: number
    h: number
    pct?: string
    lines: string[]
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
                        color: PROD_COLORS[i % PROD_COLORS.length],
                        col: 0,
                    })
                })
                const remainder = totalProduced - attributedProd * scaleFactor
                if (remainder > 0.01) {
                    col0.push({
                        id: 'prod-other',
                        label: t('pages.dashboard.energyFlow.localProduction'),
                        value: remainder,
                        color: PROD_COLORS[producers.length % PROD_COLORS.length],
                        col: 0,
                    })
                }
            } else {
                col0.push({
                    id: 'prod-local',
                    label: t('pages.dashboard.energyFlow.localProduction'),
                    value: totalProduced,
                    color: PROD_COLORS[0],
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
                color: PROD_COLORS[0],
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
                color: FLOW_LOCAL_CONS,
                col: 2,
                pct: formatPercent(selfConsumptionPct),
            })
        }
        if (gridExport > 0) {
            col2.push({
                id: 'grid-export',
                label: t('pages.dashboard.energyFlow.gridExport'),
                value: gridExport,
                color: FLOW_GRID_EXP,
                col: 2,
                pct: formatPercent(exportPct),
            })
        }

        // --- Col 3: Grid Import ---
        const col3: NDef[] = []
        if (gridImport > 0) {
            col3.push({
                id: 'grid-import',
                label: t('pages.dashboard.energyFlow.gridImport'),
                value: gridImport,
                color: CHART_GRID,
                col: 3,
            })
        }

        // --- Col 4: Individual consumers (or highlighted + Others) ---
        const col4: NDef[] = consumers.map((p, i) => ({
            id: `cons-${p.participant_id}`,
            label: p.participant_name || `Consumer ${i + 1}`,
            value: p.total_consumed_kwh,
            color: p.participant_id === '__others__' ? OTHERS_COLOR : CONS_COLORS[i % CONS_COLORS.length],
            col: 4,
        }))

        const allCols = [col0, col1, col2, col3, col4]
        if (allCols.every(c => c.length === 0)) return null

        // --- Horizontal layout: side gutters sized to the participant labels ---
        const padLeft = sidePad(col0.map(n => n.label))
        const padRight = sidePad(col4.map(n => n.label))
        const colUsable = VIEW_W - padLeft - padRight - BAR_W
        const colX = [0, 1, 2, 3, 4].map(i => Math.round(padLeft + (colUsable * i) / 4))
        const labelWidth = (pad: number) => pad - LABEL_GAP - 4

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
                const lines = def.col === 0
                    ? wrapLabel(def.label, labelWidth(padLeft))
                    : def.col === 4 ? wrapLabel(def.label, labelWidth(padRight)) : [def.label]
                const node: SNode = { ...def, y, h, lines }
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
            rawLinks.push({ id: 'total-prod->local-cons', sourceId: 'total-prod', targetId: 'local-cons', value: localCons, color: FLOW_LOCAL_CONS })
        }
        if (nMap['total-prod'] && nMap['grid-export']) {
            rawLinks.push({ id: 'total-prod->grid-export', sourceId: 'total-prod', targetId: 'grid-export', value: gridExport, color: FLOW_GRID_EXP })
        }

        // Col 2 -> Col 4: local consumption -> consumers (from_zev share)
        if (nMap['local-cons']) {
            for (const c of consumers) {
                if (c.from_zev_kwh < 0.01) continue
                const tid = `cons-${c.participant_id}`
                if (!nMap[tid]) continue
                rawLinks.push({ id: `local-cons->${tid}`, sourceId: 'local-cons', targetId: tid, value: c.from_zev_kwh, color: FLOW_LOCAL_CONS })
            }
        }

        // Col 3 -> Col 4: grid import -> consumers (from_grid share)
        if (nMap['grid-import']) {
            for (const c of consumers) {
                if (c.from_grid_kwh < 0.01) continue
                const tid = `cons-${c.participant_id}`
                if (!nMap[tid]) continue
                rawLinks.push({ id: `grid-import->${tid}`, sourceId: 'grid-import', targetId: tid, value: c.from_grid_kwh, color: CHART_GRID })
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
            return { ...lk, sy, ty, th, sx: colX[src.col] + BAR_W, tx: colX[tgt.col] }
        })

        return { nodes, links, viewH, colX }
    }, [totals, participantStats, highlightParticipantId, t])

    if (!data) return <p className="muted">{t('pages.dashboard.noData')}</p>

    const { nodes, links, viewH, colX } = data
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
                            <title>{`${src.label} → ${tgt.label}: ${formatKwh(lk.value)} kWh`}</title>
                        </path>
                        {lk.th >= 10 && hit && (
                            <text
                                x={midX}
                                y={midY}
                                textAnchor="middle"
                                dominantBaseline="central"
                                fontSize={9}
                                fill={CHART_INK}
                                fillOpacity={0.85}
                                style={{ pointerEvents: 'none' }}
                            >
                                {formatKwh(lk.value)} kWh
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
                const x = colX[n.col]
                // Center the name lines plus the kWh line on the bar
                const cy = n.y + n.h / 2
                const extra = ((n.lines.length - 1) * LABEL_LINE_H) / 2
                const nameY = (i: number) => cy - 6 - extra + i * LABEL_LINE_H
                const valueY = cy + 7 + extra

                return (
                    <g
                        key={n.id}
                        style={{ cursor: 'pointer', opacity: active ? 1 : 0.3, transition: 'opacity 200ms' }}
                        onMouseEnter={() => setHoverNode(n.id)}
                        onMouseLeave={() => setHoverNode(null)}
                    >
                        {(isLeft || isRight) && <title>{`${n.label}: ${formatKwh(n.value)} kWh`}</title>}
                        <rect x={x} y={n.y} width={BAR_W} height={n.h} fill={n.color} rx={2} />

                        {(isLeft || isRight) && (() => {
                            const tx = isLeft ? x - LABEL_GAP : x + BAR_W + LABEL_GAP
                            const anchor = isLeft ? 'end' : 'start'
                            return (
                                <>
                                    <text className="sankey-participant-label" x={tx} textAnchor={anchor} dominantBaseline="central" fontSize={LABEL_FONT} fill={CHART_INK}>
                                        {n.lines.map((line, i) => (
                                            <tspan key={i} x={tx} y={nameY(i)}>{line}</tspan>
                                        ))}
                                    </text>
                                    <text x={tx} y={valueY} textAnchor={anchor} dominantBaseline="central" fontSize={10} fill={CHART_MUTED}>{formatKwh(n.value)} kWh</text>
                                </>
                            )
                        })()}

                        {isMid && (
                            <>
                                <text x={x + BAR_W / 2} y={n.y + n.h + 14} textAnchor="middle" fontSize={10} fill={CHART_INK}>{n.label}</text>
                                <text x={x + BAR_W / 2} y={n.y + n.h + 26} textAnchor="middle" fontSize={9} fill={CHART_MUTED}>{formatKwh(n.value)} kWh</text>
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
