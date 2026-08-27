import { Skeleton } from '@mantine/core'
import { useReducedMotion } from '@mantine/hooks'

export type PageSkeletonVariant = 'page' | 'card' | 'cardList' | 'table' | 'tableRows' | 'kpiRow'

type PageSkeletonProps = {
    variant: PageSkeletonVariant
}

const KPI_COUNT = 4
const TABLE_ROWS = 5
const CARD_LIST_COUNT = 3

function Block(props: React.ComponentProps<typeof Skeleton> & { animate: boolean }) {
    const { animate, ...rest } = props
    return <Skeleton className="skeleton-block" animate={animate} {...rest} />
}

function KpiRow({ animate, withHint }: { animate: boolean; withHint: boolean }) {
    return (
        <div className="kpi-row">
            {Array.from({ length: KPI_COUNT }).map((_, i) => (
                <div key={i} className="stat-card">
                    <Block animate={animate} height={14} width="55%" mb={8} />
                    <Block animate={animate} height={28} width="45%" mb={withHint ? 6 : undefined} />
                    {withHint && <Block animate={animate} height={12} width="70%" />}
                </div>
            ))}
        </div>
    )
}

function TableRows({ animate, withTitle }: { animate: boolean; withTitle: boolean }) {
    return (
        <div className="skeleton-table-rows">
            {withTitle && <Block animate={animate} height={18} width="28%" mb={16} />}
            {Array.from({ length: TABLE_ROWS }).map((_, i) => (
                <Block key={i} animate={animate} height={36} />
            ))}
        </div>
    )
}

function CardSkeleton({ animate, titleWidth = "30%" }: { animate: boolean; titleWidth?: string }) {
    return (
        <div className="card">
            <Block animate={animate} height={18} width={titleWidth} mb={12} />
            <Block animate={animate} height={14} width="100%" mb={8} />
            <Block animate={animate} height={14} width="88%" />
        </div>
    )
}

export function PageSkeleton({ variant }: PageSkeletonProps) {
    const animate = !useReducedMotion()

    if (variant === 'kpiRow') {
        return <KpiRow animate={animate} withHint />
    }

    if (variant === 'table') {
        return (
            <div className="card">
                <TableRows animate={animate} withTitle />
            </div>
        )
    }

    if (variant === 'tableRows') {
        return <TableRows animate={animate} withTitle={false} />
    }

    if (variant === 'cardList') {
        return (
            <div className="participant-card-list">
                {Array.from({ length: CARD_LIST_COUNT }).map((_, i) => (
                    <div key={i} className="card">
                        <Block animate={animate} height={20} width="35%" mb={12} />
                        <Block animate={animate} height={14} width="100%" mb={8} />
                        <Block animate={animate} height={14} width="85%" mb={8} />
                        <Block animate={animate} height={14} width="60%" />
                    </div>
                ))}
            </div>
        )
    }

    if (variant === 'card') {
        return (
            <div className="card">
                <Block animate={animate} height={18} width="40%" mb={12} />
                <Block animate={animate} height={14} width="100%" mb={8} />
                <Block animate={animate} height={14} width="88%" mb={8} />
                <Block animate={animate} height={14} width="65%" />
            </div>
        )
    }

    // page — eyebrow + title + KPI row + 2 cards (for full-page RouteFallback)
    return (
        <div className="page-stack">
            <div>
                <Block animate={animate} height={12} width="8rem" mb={8} />
                <Block animate={animate} height={26} width="18rem" mb={8} />
                <Block animate={animate} height={14} width="26rem" />
            </div>
            <KpiRow animate={animate} withHint={false} />
            <CardSkeleton animate={animate} />
            <CardSkeleton animate={animate} />
        </div>
    )
}
