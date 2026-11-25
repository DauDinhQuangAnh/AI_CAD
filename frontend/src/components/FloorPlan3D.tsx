import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { Corner, FloorPlan, Opening } from '../types/cad'

interface FloorPlan3DProps {
  floor: FloorPlan
}

type CameraPreset = 'iso' | 'top' | 'front'

interface DoorControl {
  id: string
  pivot: THREE.Group
  baseRotY: number
  isOpen: boolean
  leafMat: THREE.MeshStandardMaterial
}

const ROOM_SLAB_COLORS: Record<string, number> = {
  commercial: 0xbae6fd,
  living: 0xbbf7d0,
  bedroom: 0xe9d5ff,
  bathroom: 0x99f6e4,
  kitchen: 0xfed7aa,
  corridor: 0xfef08a,
  utility: 0xe2e8f0,
  other: 0xf1f5f9,
}

export const FloorPlan3D: React.FC<FloorPlan3DProps> = ({ floor }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cameraApiRef = useRef<{ setPreset: (p: CameraPreset) => void } | null>(null)
  const doorsRef = useRef<DoorControl[]>([])
  const [preset, setPreset] = useState<CameraPreset>('iso')
  const [showSlabs, setShowSlabs] = useState(true)
  const [openCount, setOpenCount] = useState(0)
  const [hoveringDoor, setHoveringDoor] = useState(false)

  const totalDoors = floor.openings.filter((o) => o.type !== 'window').length

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const width = el.clientWidth || 800
    const height = el.clientHeight || 600

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#f8fafc')

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 200)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    el.innerHTML = ''
    el.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    scene.add(new THREE.AmbientLight(0xffffff, 0.75))
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.85)
    dirLight.position.set(14, 24, 12)
    scene.add(dirLight)

    const bb = floor.bounding_box
    const spanX = Math.max(4, (bb.x_max - bb.x_min) / 1000)
    const spanZ = Math.max(4, (bb.y_max - bb.y_min) / 1000)
    const maxSpan = Math.max(spanX, spanZ)
    const cx = ((bb.x_min + bb.x_max) / 2) / 1000
    const cz = ((bb.y_min + bb.y_max) / 2) / 1000

    const gridSize = Math.ceil(maxSpan * 2)
    const grid = new THREE.GridHelper(gridSize, gridSize, 0x94a3b8, 0xe2e8f0)
    scene.add(grid)

    const cornerMap = new Map<string, Corner>()
    for (const c of floor.corners) cornerMap.set(c.id, c)

    // Group openings by host wall ID
    const openingsByWall = new Map<string, Opening[]>()
    for (const op of floor.openings) {
      const list = openingsByWall.get(op.wall_id) || []
      list.push(op)
      openingsByWall.set(op.wall_id, list)
    }

    // 1. Room floor slabs
    if (showSlabs) {
      for (const sp of floor.spaces) {
        const pts = sp.boundary_corner_ids
          .map((id) => cornerMap.get(id))
          .filter((c): c is Corner => Boolean(c))
        if (pts.length < 3) continue

        const shape = new THREE.Shape()
        pts.forEach((p, idx) => {
          const x = p.x / 1000 - cx
          const y = p.y / 1000 - cz
          if (idx === 0) shape.moveTo(x, y)
          else shape.lineTo(x, y)
        })
        shape.closePath()

        const slabGeo = new THREE.ShapeGeometry(shape)
        slabGeo.rotateX(-Math.PI / 2)
        const slabMat = new THREE.MeshStandardMaterial({
          color: ROOM_SLAB_COLORS[sp.category] ?? ROOM_SLAB_COLORS.other,
          roughness: 0.9,
          side: THREE.DoubleSide,
        })
        const slab = new THREE.Mesh(slabGeo, slabMat)
        slab.position.y = 0.01
        scene.add(slab)
      }
    }

    // 2. Walls (split around openings) + 3. Interactive Hinged Doors
    const extMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.7 })
    const intMat = new THREE.MeshStandardMaterial({ color: 0x64748b, roughness: 0.8 })
    const winMat = new THREE.MeshStandardMaterial({
      color: 0x0284c7,
      roughness: 0.3,
      transparent: true,
      opacity: 0.7,
    })
    const handleMat = new THREE.MeshStandardMaterial({
      color: 0xfacc15,
      metalness: 0.6,
      roughness: 0.3,
    })
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x9f1239, roughness: 0.6 })

    const clickableMeshes: THREE.Object3D[] = []
    const doorControls: DoorControl[] = []

    for (const w of floor.walls) {
      const c1 = cornerMap.get(w.corner_start_id)
      const c2 = cornerMap.get(w.corner_end_id)
      if (!c1 || !c2) continue

      const x1 = c1.x / 1000 - cx
      const z1 = -(c1.y / 1000 - cz)
      const x2 = c2.x / 1000 - cx
      const z2 = -(c2.y / 1000 - cz)

      const wlen = Math.hypot(x2 - x1, z2 - z1)
      if (wlen < 0.05) continue

      const ux = (x2 - x1) / wlen
      const uz = (z2 - z1) / wlen
      const wallAngle = Math.atan2(z2 - z1, x2 - x1)
      const thk = Math.max(0.08, w.thickness / 1000)
      const wallH = (w.height || 2800) / 1000
      const wallMat = w.wall_type === 'exterior' ? extMat : intMat

      const wallOps = [...(openingsByWall.get(w.id) || [])].sort(
        (a, b) => a.position_along_wall_mm - b.position_along_wall_mm,
      )

      let cursor = 0
      for (const op of wallOps) {
        const opWidth = Math.min(wlen - 0.05, Math.max(0.3, op.width / 1000))
        const opStart = Math.max(cursor, Math.min(wlen - opWidth, op.position_along_wall_mm / 1000))
        const opEnd = Math.min(wlen, opStart + opWidth)
        const opHeight = Math.min(wallH - 0.1, (op.height || 2100) / 1000)

        // Solid wall segment before this opening
        const segLen = opStart - cursor
        if (segLen > 0.04) {
          const mid = cursor + segLen / 2
          const geo = new THREE.BoxGeometry(segLen, wallH, thk)
          const mesh = new THREE.Mesh(geo, wallMat)
          mesh.position.set(x1 + ux * mid, wallH / 2, z1 + uz * mid)
          mesh.rotation.y = -wallAngle
          scene.add(mesh)
        }

        // Lintel above opening
        const lintelH = wallH - opHeight
        if (lintelH > 0.05) {
          const opMid = opStart + (opEnd - opStart) / 2
          const lintelGeo = new THREE.BoxGeometry(opEnd - opStart, lintelH, thk)
          const lintel = new THREE.Mesh(lintelGeo, wallMat)
          lintel.position.set(x1 + ux * opMid, opHeight + lintelH / 2, z1 + uz * opMid)
          lintel.rotation.y = -wallAngle
          scene.add(lintel)
        }

        if (op.type === 'window') {
          const opMid = opStart + (opEnd - opStart) / 2
          const winGeo = new THREE.BoxGeometry(opEnd - opStart, opHeight * 0.6, thk * 0.6)
          const winMesh = new THREE.Mesh(winGeo, winMat)
          winMesh.position.set(x1 + ux * opMid, opHeight * 0.65, z1 + uz * opMid)
          winMesh.rotation.y = -wallAngle
          scene.add(winMesh)
        } else {
          // Door threshold
          const actualW = opEnd - opStart
          const opMid = opStart + actualW / 2
          const threshGeo = new THREE.BoxGeometry(actualW, 0.03, thk + 0.02)
          const thresh = new THREE.Mesh(threshGeo, frameMat)
          thresh.position.set(x1 + ux * opMid, 0.015, z1 + uz * opMid)
          thresh.rotation.y = -wallAngle
          scene.add(thresh)

          // Hinged pivot centered cleanly at (opStart, 0) so door rotates around hinge edge
          const pivot = new THREE.Group()
          pivot.position.set(x1 + ux * opStart, 0, z1 + uz * opStart)
          const baseRotY = -wallAngle
          pivot.rotation.y = baseRotY

          const leafMat = new THREE.MeshStandardMaterial({
            color: 0xe11d48,
            roughness: 0.45,
          })
          const leafGeo = new THREE.BoxGeometry(actualW, opHeight, 0.05)
          const leaf = new THREE.Mesh(leafGeo, leafMat)
          leaf.position.set(actualW / 2, opHeight / 2, 0)

          const handleGeo = new THREE.BoxGeometry(0.11, 0.04, 0.12)
          const handle = new THREE.Mesh(handleGeo, handleMat)
          handle.position.set(actualW - 0.12, 1.0, 0)

          const control: DoorControl = {
            id: op.id,
            pivot,
            baseRotY,
            isOpen: false,
            leafMat,
          }
          leaf.userData = { doorControl: control }
          handle.userData = { doorControl: control }

          pivot.add(leaf)
          pivot.add(handle)
          scene.add(pivot)

          clickableMeshes.push(leaf, handle)
          doorControls.push(control)
        }

        cursor = opEnd
      }

      // Trailing solid wall segment
      const tailLen = wlen - cursor
      if (tailLen > 0.04) {
        const mid = cursor + tailLen / 2
        const geo = new THREE.BoxGeometry(tailLen, wallH, thk)
        const mesh = new THREE.Mesh(geo, wallMat)
        mesh.position.set(x1 + ux * mid, wallH / 2, z1 + uz * mid)
        mesh.rotation.y = -wallAngle
        scene.add(mesh)
      }
    }

    doorsRef.current = doorControls
    setOpenCount(0)

    const applyPreset = (p: CameraPreset) => {
      const prevDamp = controls.enableDamping
      controls.enableDamping = false
      // Compensate for narrow Split-view panes (aspect < 1) so horizontal edges never clip
      const aspectScale = Math.max(1.0, 1.05 / Math.max(0.45, camera.aspect))
      const dist = maxSpan * aspectScale
      if (p === 'top') {
        camera.position.set(0, dist * 1.9, 0.01)
        controls.target.set(0, 0, 0)
      } else if (p === 'front') {
        camera.position.set(0, dist * 0.55, dist * 1.8)
        controls.target.set(0, 1.0, 0)
      } else {
        camera.position.set(dist * 0.85, dist * 1.5, dist * 1.5)
        controls.target.set(0, 0.8, 0)
      }
      controls.update()
      controls.enableDamping = prevDamp
    }

    cameraApiRef.current = { setPreset: applyPreset }
    applyPreset(preset)

    const raycaster = new THREE.Raycaster()
    const pointerNdc = new THREE.Vector2()
    let downPos = { x: 0, y: 0 }

    const updateNdc = (clientX: number, clientY: number) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointerNdc.x = ((clientX - rect.left) / rect.width) * 2 - 1
      pointerNdc.y = -((clientY - rect.top) / rect.height) * 2 + 1
    }

    const onPointerDown = (e: PointerEvent) => {
      downPos = { x: e.clientX, y: e.clientY }
    }

    const onPointerMove = (e: PointerEvent) => {
      if (clickableMeshes.length === 0) return
      updateNdc(e.clientX, e.clientY)
      raycaster.setFromCamera(pointerNdc, camera)
      const hits = raycaster.intersectObjects(clickableMeshes, false)
      setHoveringDoor(hits.length > 0)
    }

    const onPointerUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 5) return
      if (clickableMeshes.length === 0) return
      updateNdc(e.clientX, e.clientY)
      raycaster.setFromCamera(pointerNdc, camera)
      const hits = raycaster.intersectObjects(clickableMeshes, false)
      if (hits.length > 0) {
        const ctrl = hits[0].object.userData?.doorControl as DoorControl | undefined
        if (ctrl) {
          ctrl.isOpen = !ctrl.isOpen
          ctrl.leafMat.color.setHex(ctrl.isOpen ? 0x10b981 : 0xe11d48)
          setOpenCount(doorControls.filter((d) => d.isOpen).length)
        }
      }
    }

    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    renderer.domElement.addEventListener('pointermove', onPointerMove)
    renderer.domElement.addEventListener('pointerup', onPointerUp)

    let animId = 0
    const animate = () => {
      animId = requestAnimationFrame(animate)
      for (const dc of doorControls) {
        const target = dc.baseRotY + (dc.isOpen ? Math.PI / 2 : 0)
        dc.pivot.rotation.y += (target - dc.pivot.rotation.y) * 0.16
      }
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    let resizeRaf = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(resizeRaf)
      resizeRaf = requestAnimationFrame(() => {
        if (!el) return
        const nw = el.clientWidth
        const nh = el.clientHeight
        if (nw > 0 && nh > 0) {
          camera.aspect = nw / nh
          camera.updateProjectionMatrix()
          renderer.setSize(nw, nh)
          applyPreset(preset)
        }
      })
    })
    observer.observe(el)

    return () => {
      cancelAnimationFrame(animId)
      cancelAnimationFrame(resizeRaf)
      observer.disconnect()
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      renderer.domElement.removeEventListener('pointermove', onPointerMove)
      renderer.domElement.removeEventListener('pointerup', onPointerUp)
      controls.dispose()
      renderer.dispose()
      cameraApiRef.current = null
      doorsRef.current = []
    }
  }, [floor, showSlabs])

  const handlePreset = (next: CameraPreset) => {
    setPreset(next)
    cameraApiRef.current?.setPreset(next)
  }

  const toggleAllDoors = () => {
    const anyClosed = doorsRef.current.some((d) => !d.isOpen)
    for (const d of doorsRef.current) {
      d.isOpen = anyClosed
      d.leafMat.color.setHex(anyClosed ? 0x10b981 : 0xe11d48)
    }
    setOpenCount(anyClosed ? doorsRef.current.length : 0)
  }

  return (
    <div className="relative h-full w-full">
      <div className="absolute left-3 top-3 z-10 flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-white/95 px-2.5 py-1.5 text-xs text-slate-700 shadow-sm backdrop-blur">
        {(['iso', 'top', 'front'] as CameraPreset[]).map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => handlePreset(p)}
            className={`rounded-md px-2 py-0.5 font-medium uppercase ${
              preset === p
                ? 'bg-sky-100 text-sky-700'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            {p}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-slate-200" />
        <label className="flex cursor-pointer items-center gap-1.5 px-1">
          <input
            type="checkbox"
            checked={showSlabs}
            onChange={(e) => setShowSlabs(e.target.checked)}
            className="accent-sky-600"
          />
          Floor Slabs
        </label>
        {totalDoors > 0 && (
          <>
            <span className="mx-1 h-4 w-px bg-slate-200" />
            <button
              type="button"
              onClick={toggleAllDoors}
              className="rounded-md bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-700 hover:bg-rose-100"
            >
              {openCount === totalDoors ? 'Đóng tất cả' : 'Mở tất cả'} ({openCount}/{totalDoors})
            </button>
          </>
        )}
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-[calc(100%-1.5rem)] truncate rounded-lg border border-slate-200 bg-white/90 px-2.5 py-1 text-[11px] font-medium text-slate-600 shadow-sm backdrop-blur">
        Click cửa để đóng/mở 90° · Kéo để xoay
      </div>

      <div
        ref={containerRef}
        className={`h-full w-full ${hoveringDoor ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'}`}
      />
    </div>
  )
}
