import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  Box,
  Download,
  FileUp,
  FolderKanban,
  Layers,
  Loader2,
  Play,
  Ruler,
  Sparkles,
  Square,
} from 'lucide-react'
import { FloorPlan2D } from './components/FloorPlan2D'
import { FloorPlan3D } from './components/FloorPlan3D'
import { ProjectDashboard } from './components/ProjectDashboard'
import type { AnalyzeResponse, ProjectSummary } from './types/cad'

type NavTab = 'projects' | 'studio'
type ViewMode = '2d' | '3d' | 'split'
type InspectorTab = 'spaces' | 'elements' | 'export'

export function App() {
  const [navTab, setNavTab] = useState<NavTab>('projects')
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [result, setResult] = useState<AnalyzeResponse | null>(null)
  const [activeFloorIdx, setActiveFloorIdx] = useState(0)
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('split')
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('spaces')
  const [useLlm, setUseLlm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshProjects = useCallback(async () => {
    try {
      const res = await fetch('/api/projects')
      if (!res.ok) return
      const data = await res.json()
      setProjects(data.projects || [])
    } catch {
      // Ignore transient fetch errors on startup
    }
  }, [])

  useEffect(() => {
    refreshProjects()
  }, [refreshProjects])

  const openResult = (data: AnalyzeResponse) => {
    setResult(data)
    setActiveFloorIdx(0)
    setSelectedSpaceId(null)
    setNavTab('studio')
  }

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Chỉ hỗ trợ file .PDF vector.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('use_llm', String(useLlm))
      const res = await fetch('/api/analyze', { method: 'POST', body: form })
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error(errBody.detail || `HTTP ${res.status}`)
      }
      const data: AnalyzeResponse = await res.json()
      openResult(data)
      await refreshProjects()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lỗi xử lý PDF')
    } finally {
      setLoading(false)
    }
  }

  const handleRunSample = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/analyze-sample?use_llm=${useLlm}`, {
        method: 'POST',
      })
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error(errBody.detail || `HTTP ${res.status}`)
      }
      const data: AnalyzeResponse = await res.json()
      openResult(data)
      await refreshProjects()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể chạy file mẫu')
    } finally {
      setLoading(false)
    }
  }

  const handleOpenProject = async (projectId: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/projects/${projectId}`)
      if (!res.ok) throw new Error('Không thể tải dữ liệu dự án.')
      const data: AnalyzeResponse = await res.json()
      openResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lỗi tải dự án')
    } finally {
      setLoading(false)
    }
  }

  const handleRenameProject = async (projectId: string, name: string) => {
    const res = await fetch(`/api/projects/${projectId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (res.ok) {
      await refreshProjects()
      if (result?.job_id === projectId) {
        setResult((prev) =>
          prev
            ? {
                ...prev,
                document: {
                  ...prev.document,
                  project_metadata: {
                    ...prev.document.project_metadata,
                    project_name: name,
                  },
                },
              }
            : prev,
        )
      }
    }
  }

  const handleDeleteProject = async (projectId: string) => {
    const res = await fetch(`/api/projects/${projectId}`, { method: 'DELETE' })
    if (res.ok) {
      await refreshProjects()
      if (result?.job_id === projectId) {
        setResult(null)
        setNavTab('projects')
      }
    }
  }

  const floor = result?.document.floors[activeFloorIdx] ?? null

  const wallStats = useMemo(() => {
    if (!floor) return { ext: 0, int: 0 }
    let ext = 0
    let int = 0
    for (const w of floor.walls) {
      if (w.wall_type === 'exterior') ext += 1
      else int += 1
    }
    return { ext, int }
  }, [floor])

  return (
    <div className="flex h-screen flex-col bg-slate-50 text-slate-900">
      {/* Top Header */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2.5 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-600 text-white shadow-sm">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold tracking-tight text-slate-900">
                AI_CAD Studio
              </h1>
              {navTab === 'studio' && result && (
                <>
                  <span className="text-slate-300">/</span>
                  <span className="text-xs font-medium text-slate-700">
                    {result.document.project_metadata.project_name}
                  </span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                    {result.document.project_metadata.scale_ratio}
                  </span>
                </>
              )}
            </div>
            <p className="text-[11px] text-slate-500">
              Architectural Floor Plan Analysis · 2D Vector CAD (.DXF) &amp; 3D Extrusion
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {navTab === 'studio' && (
            <button
              type="button"
              onClick={() => setNavTab('projects')}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Dự án ({projects.length})
            </button>
          )}

          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-100">
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(e) => setUseLlm(e.target.checked)}
              className="accent-sky-600"
            />
            <Sparkles className="h-3.5 w-3.5 text-amber-500" />
            Gemini Vision
          </label>

          <button
            type="button"
            onClick={handleRunSample}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5 text-emerald-600" />
            Test mẫu
          </button>

          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-sky-500">
            <FileUp className="h-3.5 w-3.5" />
            Upload PDF
            <input
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleUpload(file)
                e.target.value = ''
              }}
            />
          </label>
        </div>
      </header>

      {/* Body with Left Navigation Rail */}
      <div className="relative flex min-h-0 flex-1">
        {/* Left Navigation Rail */}
        <nav className="flex w-14 shrink-0 flex-col items-center gap-2 border-r border-slate-200 bg-white py-3">
          <button
            type="button"
            onClick={() => setNavTab('projects')}
            className={`flex h-10 w-10 flex-col items-center justify-center rounded-xl transition ${
              navTab === 'projects'
                ? 'bg-sky-50 text-sky-700 ring-1 ring-sky-200'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
            }`}
            title="Quản lý dự án"
          >
            <FolderKanban className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={() => result && setNavTab('studio')}
            disabled={!result}
            className={`flex h-10 w-10 flex-col items-center justify-center rounded-xl transition disabled:opacity-35 ${
              navTab === 'studio'
                ? 'bg-sky-50 text-sky-700 ring-1 ring-sky-200'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
            }`}
            title="CAD Studio 2D/3D"
          >
            <Ruler className="h-5 w-5" />
          </button>
        </nav>

        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 z-40 flex flex-col items-center justify-center gap-3 bg-white/80 backdrop-blur-sm">
            <Loader2 className="h-8 w-8 animate-spin text-sky-600" />
            <p className="text-sm font-medium text-slate-700">
              Đang xử lý hình học &amp; ngữ nghĩa bản vẽ...
            </p>
          </div>
        )}

        {/* Error Toast */}
        {error && (
          <div className="absolute left-1/2 top-4 z-30 -translate-x-1/2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-medium text-rose-700 shadow-md">
            {error}
          </div>
        )}

        {/* Main View */}
        {navTab === 'projects' || !floor || !result ? (
          <div className="min-w-0 flex-1">
            <ProjectDashboard
              projects={projects}
              loading={loading}
              useLlm={useLlm}
              onToggleLlm={setUseLlm}
              onUploadPdf={handleUpload}
              onRunSample={handleRunSample}
              onOpenProject={handleOpenProject}
              onRenameProject={handleRenameProject}
              onDeleteProject={handleDeleteProject}
            />
          </div>
        ) : (
          <div className="flex min-w-0 flex-1">
            {/* 2D / 3D Canvas Area */}
            <main className="flex min-w-0 flex-1 flex-col">
              {/* Sub-toolbar: Floor Tabs & View Mode */}
              <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-1.5">
                <div className="flex items-center gap-1.5">
                  {result.document.floors.map((f, idx) => (
                    <button
                      key={f.floor_id}
                      type="button"
                      onClick={() => {
                        setActiveFloorIdx(idx)
                        setSelectedSpaceId(null)
                      }}
                      className={`rounded-lg px-3 py-1 text-xs font-medium transition ${
                        idx === activeFloorIdx
                          ? 'bg-white text-sky-700 shadow-sm ring-1 ring-slate-200'
                          : 'text-slate-600 hover:bg-slate-200/70 hover:text-slate-900'
                      }`}
                    >
                      {f.floor_name}
                      {f.elevation_peil != null && (
                        <span className="ml-1.5 text-[10px] text-slate-400">
                          ({f.elevation_peil > 0 ? `+${f.elevation_peil}` : f.elevation_peil})
                        </span>
                      )}
                    </button>
                  ))}
                </div>

                <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 text-xs shadow-sm">
                  <button
                    type="button"
                    onClick={() => setViewMode('2d')}
                    className={`flex items-center gap-1 rounded-md px-2.5 py-1 ${
                      viewMode === '2d'
                        ? 'bg-sky-50 font-medium text-sky-700'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <Square className="h-3.5 w-3.5" /> 2D
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode('3d')}
                    className={`flex items-center gap-1 rounded-md px-2.5 py-1 ${
                      viewMode === '3d'
                        ? 'bg-sky-50 font-medium text-sky-700'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <Box className="h-3.5 w-3.5" /> 3D
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode('split')}
                    className={`rounded-md px-2.5 py-1 ${
                      viewMode === 'split'
                        ? 'bg-sky-50 font-medium text-sky-700'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    Split
                  </button>
                </div>
              </div>

              {/* Viewport */}
              <div className="flex min-h-0 flex-1">
                {(viewMode === '2d' || viewMode === 'split') && (
                  <div className={viewMode === 'split' ? 'w-1/2 border-r border-slate-200' : 'w-full'}>
                    <FloorPlan2D
                      floor={floor}
                      selectedSpaceId={selectedSpaceId}
                      onSelectSpace={setSelectedSpaceId}
                    />
                  </div>
                )}
                {(viewMode === '3d' || viewMode === 'split') && (
                  <div className={viewMode === 'split' ? 'w-1/2' : 'w-full'}>
                    <FloorPlan3D floor={floor} />
                  </div>
                )}
              </div>
            </main>

            {/* Right Tabbed Inspector */}
            <aside className="flex w-80 shrink-0 flex-col border-l border-slate-200 bg-white">
              {/* Summary Strip */}
              <div className="grid grid-cols-3 gap-2 border-b border-slate-200 p-3 text-center">
                <div className="rounded-xl bg-slate-100 p-2">
                  <div className="text-base font-bold text-slate-900">
                    {floor.walls.length}
                  </div>
                  <div className="text-[11px] text-slate-500">Tường</div>
                </div>
                <div className="rounded-xl bg-rose-50 p-2">
                  <div className="text-base font-bold text-rose-600">
                    {floor.openings.length}
                  </div>
                  <div className="text-[11px] text-slate-500">Cửa</div>
                </div>
                <div className="rounded-xl bg-sky-50 p-2">
                  <div className="text-base font-bold text-sky-700">
                    {floor.spaces.length}
                  </div>
                  <div className="text-[11px] text-slate-500">Phòng</div>
                </div>
              </div>

              {/* Inspector Tabs */}
              <div className="grid grid-cols-3 border-b border-slate-200 bg-slate-50/70 text-xs font-medium">
                {(
                  [
                    ['spaces', 'Phòng'],
                    ['elements', 'Cấu kiện'],
                    ['export', 'Xuất file'],
                  ] as [InspectorTab, string][]
                ).map(([tabKey, label]) => (
                  <button
                    key={tabKey}
                    type="button"
                    onClick={() => setInspectorTab(tabKey)}
                    className={`border-b-2 py-2 transition ${
                      inspectorTab === tabKey
                        ? 'border-sky-600 bg-white text-sky-700'
                        : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {/* Tab Content */}
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {inspectorTab === 'spaces' && (
                  <div className="space-y-2">
                    {floor.spaces.map((sp) => {
                      const selected = selectedSpaceId === sp.id
                      const err = sp.area_error_pct
                      const errBadge =
                        err == null
                          ? null
                          : err <= 5
                            ? 'bg-emerald-50 text-emerald-700'
                            : err <= 15
                              ? 'bg-amber-50 text-amber-700'
                              : 'bg-rose-50 text-rose-700'

                      return (
                        <button
                          key={sp.id}
                          type="button"
                          onClick={() => setSelectedSpaceId(selected ? null : sp.id)}
                          className={`w-full rounded-xl border p-2.5 text-left text-xs transition ${
                            selected
                              ? 'border-sky-400 bg-sky-50/70 shadow-sm'
                              : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                          }`}
                        >
                          <div className="flex items-center justify-between font-semibold text-slate-900">
                            <span>{sp.name}</span>
                            <span className="text-sky-700">
                              {sp.calculated_area_m2 != null
                                ? `${sp.calculated_area_m2.toFixed(2)} m²`
                                : '—'}
                            </span>
                          </div>
                          <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                            <span>{sp.name_vn || sp.category}</span>
                            <div className="flex items-center gap-1.5">
                              {sp.nominal_area_m2 != null && (
                                <span>Gốc: {sp.nominal_area_m2.toFixed(2)} m²</span>
                              )}
                              {errBadge && err != null && (
                                <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${errBadge}`}>
                                  ±{err.toFixed(1)}%
                                </span>
                              )}
                            </div>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}

                {inspectorTab === 'elements' && (
                  <div className="space-y-3 text-xs">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <div className="font-semibold text-slate-800">Phân loại tường</div>
                      <div className="mt-2 space-y-1.5 text-slate-600">
                        <div className="flex justify-between">
                          <span>Tường bao (Exterior)</span>
                          <span className="font-semibold text-slate-900">{wallStats.ext}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Tường ngăn (Interior)</span>
                          <span className="font-semibold text-slate-900">{wallStats.int}</span>
                        </div>
                      </div>
                    </div>

                    <div>
                      <div className="mb-1.5 font-semibold text-slate-700">
                        Cửa &amp; Lỗ mở ({floor.openings.length})
                      </div>
                      <div className="space-y-1">
                        {floor.openings.map((op) => (
                          <div
                            key={op.id}
                            className="flex items-center justify-between rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px]"
                          >
                            <span className="font-medium text-slate-700">{op.type}</span>
                            <span className="font-mono text-slate-500">
                              {op.width.toFixed(0)} × {op.height.toFixed(0)} mm
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {inspectorTab === 'export' && (
                  <div className="space-y-3 text-xs">
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-1.5">
                      <div className="font-semibold text-slate-800">Thông số dự án</div>
                      <div className="flex justify-between text-slate-600">
                        <span>Mã dự án:</span>
                        <span className="font-mono font-medium text-slate-900">
                          {result.document.project_metadata.project_code || '—'}
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-600">
                        <span>Tỷ lệ:</span>
                        <span className="font-mono font-medium text-slate-900">
                          {result.document.project_metadata.scale_ratio}
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-600">
                        <span>Địa chỉ:</span>
                        <span className="font-medium text-slate-900">
                          {result.document.project_metadata.address || '—'}
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-600">
                        <span>Cao độ PEIL:</span>
                        <span className="font-mono font-medium text-slate-900">
                          {floor.elevation_peil != null ? `${floor.elevation_peil} mm` : '—'}
                        </span>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <a
                        href={result.downloads.dxf}
                        download
                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-3 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-500"
                      >
                        <Download className="h-4 w-4" /> Tải AutoCAD (.DXF)
                      </a>
                      <a
                        href={result.downloads.floorplanner}
                        download
                        className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <Download className="h-3.5 w-3.5" /> Tải Floorplanner JSON
                      </a>
                      <a
                        href={result.downloads.schema}
                        download
                        className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <Download className="h-3.5 w-3.5" /> Tải Unified Schema JSON
                      </a>
                    </div>
                  </div>
                )}
              </div>
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}

export default App
