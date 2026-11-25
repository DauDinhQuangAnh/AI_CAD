import React, { useEffect, useId, useMemo, useRef, useState } from 'react'
import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'
import type { Corner, Dimension, FloorPlan, Opening, Space, Wall } from '../types/cad'

interface FloorPlan2DProps {
  floor: FloorPlan
  selectedSpaceId: string | null
  onSelectSpace: (id: string | null) => void
}

interface ViewBox {
  x: number
  y: number
  w: number
  h: number
}

const CATEGORY_COLORS: Record<string, string> = {
  commercial: 'rgba(14, 165, 233, 0.14)',
  living: 'rgba(34, 197, 94, 0.14)',
  bedroom: 'rgba(168, 85, 247, 0.14)',
  bathroom: 'rgba(20, 184, 166, 0.16)',
  kitchen: 'rgba(249, 115, 22, 0.14)',
  corridor: 'rgba(234, 179, 8, 0.14)',
  utility: 'rgba(148, 163, 184, 0.16)',
  other: 'rgba(148, 163, 184, 0.12)',
}

export const FloorPlan2D: React.FC<FloorPlan2DProps> = ({
  floor,
  selectedSpaceId,
  onSelectSpace,
}) => {
  const gridPatternId = useId()
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragStateRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    lastX: number
    lastY: number
    moved: boolean
  } | null>(null)

  const [isPanning, setIsPanning] = useState(false)
  const [showRooms, setShowRooms] = useState(true)
  const [showDoors, setShowDoors] = useState(true)
  const [showGrid, setShowGrid] = useState(true)
  const [showDims, setShowDims] = useState(false)

  const cornerMap = useMemo(() => {
    const map = new Map<string, Corner>()
    for (const c of floor.corners) map.set(c.id, c)
    return map
  }, [floor.corners])

  const wallMap = useMemo(() => {
    const map = new Map<string, Wall>()
    for (const w of floor.walls) map.set(w.id, w)
    return map
  }, [floor.walls])

  const { initialViewBox, maxY } = useMemo(() => {
    const bb = floor.bounding_box
    const pad = 1000
    const w = Math.max(1000, bb.x_max - bb.x_min)
    const h = Math.max(1000, bb.y_max - bb.y_min)
    return {
      initialViewBox: {
        x: bb.x_min - pad,
        y: -pad,
        w: w + pad * 2,
        h: h + pad * 2,
      },
      maxY: bb.y_max + bb.y_min,
    }
  }, [floor.bounding_box])

  const [vb, setVb] = useState<ViewBox>(initialViewBox)

  useEffect(() => {
    setVb(initialViewBox)
  }, [initialViewBox])

  const toSvgY = (y: number) => maxY - y

  const zoomAt = (factor: number, normX = 0.5, normY = 0.5) => {
    setVb((prev) => {
      const minW = initialViewBox.w * 0.08
      const maxW = initialViewBox.w * 4.0
      const nextW = Math.min(maxW, Math.max(minW, prev.w * factor))
      const scale = nextW / prev.w
      const nextH = prev.h * scale
      return {
        x: prev.x + (prev.w - nextW) * normX,
        y: prev.y + (prev.h - nextH) * normY,
        w: nextW,
        h: nextH,
      }
    })
  }

  const handleWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault()
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const normX = rect.width > 0 ? (e.clientX - rect.left) / rect.width : 0.5
    const normY = rect.height > 0 ? (e.clientY - rect.top) / rect.height : 0.5
    const factor = e.deltaY < 0 ? 0.86 : 1.16
    zoomAt(factor, normX, normY)
  }

  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0 && e.button !== 1) return
    e.currentTarget.setPointerCapture(e.pointerId)
    dragStateRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      moved: false,
    }
    setIsPanning(true)
  }

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragStateRef.current
    const svg = svgRef.current
    if (!drag || !svg) return

    const dxPx = e.clientX - drag.lastX
    const dyPx = e.clientY - drag.lastY
    if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 4) {
      drag.moved = true
    }
    drag.lastX = e.clientX
    drag.lastY = e.clientY

    const rect = svg.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return

    const scale = Math.max(vb.w / rect.width, vb.h / rect.height)
    setVb((prev) => ({
      ...prev,
      x: prev.x - dxPx * scale,
      y: prev.y - dyPx * scale,
    }))
  }

  const handlePointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (dragStateRef.current?.pointerId === e.pointerId) {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        // Ignore if not captured
      }
      dragStateRef.current = null
      setIsPanning(false)
    }
  }

  const zoomPct = Math.round((initialViewBox.w / vb.w) * 100)

  return (
    <div className="relative h-full w-full overflow-hidden bg-white select-none">
      {/* Toolbar */}
      <div className="absolute left-3 top-3 z-10 flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-white/95 px-2.5 py-1.5 text-xs text-slate-700 shadow-sm backdrop-blur">
        <button
          type="button"
          onClick={() => zoomAt(0.8)}
          className="rounded-md p-1 hover:bg-slate-100"
          title="Zoom in"
        >
          <ZoomIn className="h-4 w-4" />
        </button>
        <span className="min-w-[3rem] text-center font-mono text-[11px] text-slate-500">
          {zoomPct}%
        </span>
        <button
          type="button"
          onClick={() => zoomAt(1.25)}
          className="rounded-md p-1 hover:bg-slate-100"
          title="Zoom out"
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => setVb(initialViewBox)}
          className="rounded-md p-1 hover:bg-slate-100"
          title="Reset view"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
        <span className="mx-1 h-4 w-px bg-slate-200" />
        <label className="flex cursor-pointer items-center gap-1.5 px-1">
          <input
            type="checkbox"
            checked={showGrid}
            onChange={(e) => setShowGrid(e.target.checked)}
            className="accent-sky-600"
          />
          Grid
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 px-1">
          <input
            type="checkbox"
            checked={showRooms}
            onChange={(e) => setShowRooms(e.target.checked)}
            className="accent-sky-600"
          />
          Rooms
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 px-1">
          <input
            type="checkbox"
            checked={showDoors}
            onChange={(e) => setShowDoors(e.target.checked)}
            className="accent-sky-600"
          />
          Doors
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 px-1">
          <input
            type="checkbox"
            checked={showDims}
            onChange={(e) => setShowDims(e.target.checked)}
            className="accent-sky-600"
          />
          Dims
        </label>
      </div>

      {/* Bottom Scale Bar */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-w-[calc(100%-1.5rem)] items-center gap-2 truncate rounded-lg border border-slate-200 bg-white/90 px-2.5 py-1 text-[11px] font-medium text-slate-600 shadow-sm backdrop-blur">
        <span>1000 mm = 1 m</span>
        <span className="h-3 w-px bg-slate-200" />
        <span>Kéo pan · Cuộn zoom</span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        className={`h-full w-full touch-none ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        {showGrid && (
          <defs>
            <pattern
              id={gridPatternId}
              width="1000"
              height="1000"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M 1000 0 L 0 0 0 1000"
                fill="none"
                stroke="#f1f5f9"
                strokeWidth="25"
              />
            </pattern>
          </defs>
        )}
        {showGrid && (
          <rect
            x={vb.x - 10000}
            y={vb.y - 10000}
            width={vb.w + 20000}
            height={vb.h + 20000}
            fill={`url(#${gridPatternId})`}
          />
        )}

        {/* Rooms */}
        {showRooms &&
          floor.spaces.map((sp: Space) => {
            const pts = sp.boundary_corner_ids
              .map((id) => cornerMap.get(id))
              .filter((c): c is Corner => Boolean(c))
            if (pts.length < 3) return null
            const pointsAttr = pts.map((p) => `${p.x},${toSvgY(p.y)}`).join(' ')
            const cx = pts.reduce((acc, p) => acc + p.x, 0) / pts.length
            const cy = pts.reduce((acc, p) => acc + toSvgY(p.y), 0) / pts.length
            const isSelected = selectedSpaceId === sp.id
            return (
              <g
                key={sp.id}
                onClick={() => {
                  if (dragStateRef.current?.moved) return
                  onSelectSpace(isSelected ? null : sp.id)
                }}
                className="cursor-pointer"
              >
                <polygon
                  points={pointsAttr}
                  fill={
                    isSelected
                      ? 'rgba(14, 165, 233, 0.28)'
                      : CATEGORY_COLORS[sp.category] || CATEGORY_COLORS.other
                  }
                  stroke={isSelected ? '#0284c7' : '#cbd5e1'}
                  strokeWidth={isSelected ? 45 : 20}
                />
                <text
                  x={cx}
                  y={cy}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="#0f172a"
                  fontSize={160}
                  fontWeight={600}
                >
                  {sp.name}
                </text>
                {sp.calculated_area_m2 != null && (
                  <text
                    x={cx}
                    y={cy + 210}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill="#475569"
                    fontSize={130}
                  >
                    {sp.calculated_area_m2.toFixed(2)} m²
                  </text>
                )}
              </g>
            )
          })}

        {/* Walls */}
        {floor.walls.map((w: Wall) => {
          const c1 = cornerMap.get(w.corner_start_id)
          const c2 = cornerMap.get(w.corner_end_id)
          if (!c1 || !c2) return null
          return (
            <line
              key={w.id}
              x1={c1.x}
              y1={toSvgY(c1.y)}
              x2={c2.x}
              y2={toSvgY(c2.y)}
              stroke={w.wall_type === 'exterior' ? '#0f172a' : '#334155'}
              strokeWidth={Math.max(60, w.thickness)}
              strokeLinecap="square"
            />
          )
        })}

        {/* Openings (Architectural Door Leaf + 90-deg Swing Arc) */}
        {showDoors &&
          floor.openings.map((op: Opening) => {
            const w = wallMap.get(op.wall_id)
            if (!w) return null
            const c1 = cornerMap.get(w.corner_start_id)
            const c2 = cornerMap.get(w.corner_end_id)
            if (!c1 || !c2) return null
            const dx = c2.x - c1.x
            const dy = toSvgY(c2.y) - toSvgY(c1.y)
            const len = Math.hypot(dx, dy)
            if (len < 1) return null
            const ux = dx / len
            const uy = dy / len
            const nx = -uy
            const ny = ux
            const sx = c1.x + ux * op.position_along_wall_mm
            const sy = toSvgY(c1.y) + uy * op.position_along_wall_mm
            const ex = sx + ux * op.width
            const ey = sy + uy * op.width
            const lx = sx + nx * op.width
            const ly = sy + ny * op.width
            return (
              <g key={op.id}>
                {/* Clear wall gap */}
                <line
                  x1={sx}
                  y1={sy}
                  x2={ex}
                  y2={ey}
                  stroke="#ffffff"
                  strokeWidth={Math.max(80, w.thickness + 20)}
                />
                {/* Door leaf */}
                <line
                  x1={sx}
                  y1={sy}
                  x2={lx}
                  y2={ly}
                  stroke="#e11d48"
                  strokeWidth={55}
                  strokeLinecap="round"
                />
                {/* 90-deg swing arc */}
                <path
                  d={`M ${ex} ${ey} A ${op.width} ${op.width} 0 0 1 ${lx} ${ly}`}
                  fill="none"
                  stroke="#fb7185"
                  strokeWidth={22}
                  strokeDasharray="60 40"
                />
              </g>
            )
          })}

        {/* Dimension Annotations */}
        {showDims &&
          (floor.dimensions || []).map((dim: Dimension) => {
            const mx = (dim.start_point.x + dim.end_point.x) / 2
            const my = toSvgY((dim.start_point.y + dim.end_point.y) / 2)
            return (
              <g key={dim.id} className="pointer-events-none">
                <rect
                  x={mx - 240}
                  y={my - 110}
                  width={480}
                  height={220}
                  rx={40}
                  fill="rgba(255,255,255,0.9)"
                  stroke="#0284c7"
                  strokeWidth={18}
                />
                <text
                  x={mx}
                  y={my}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="#0369a1"
                  fontSize={140}
                  fontWeight={600}
                >
                  {dim.text}
                </text>
              </g>
            )
          })}
      </svg>
    </div>
  )
}
