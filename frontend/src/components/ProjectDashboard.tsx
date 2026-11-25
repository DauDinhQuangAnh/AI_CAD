import React, { useMemo, useState } from 'react'
import {
  Check,
  Download,
  FileText,
  FileUp,
  FolderOpen,
  Layers,
  Pencil,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import type { ProjectSummary } from '../types/cad'

interface ProjectDashboardProps {
  projects: ProjectSummary[]
  useLlm: boolean
  onToggleLlm: (val: boolean) => void
  onUploadPdf: (file: File) => void
  onOpenProject: (projectId: string) => void
  onRenameProject: (projectId: string, name: string) => Promise<void>
  onDeleteProject: (projectId: string) => Promise<void>
}

type SortKey = 'newest' | 'area' | 'name'

export const ProjectDashboard: React.FC<ProjectDashboardProps> = ({
  projects,
  useLlm,
  onToggleLlm,
  onUploadPdf,
  onOpenProject,
  onRenameProject,
  onDeleteProject,
}) => {
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState<SortKey>('newest')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  const stats = useMemo(() => {
    const totalFloors = projects.reduce((acc, p) => acc + p.floors_count, 0)
    const totalRooms = projects.reduce((acc, p) => acc + p.total_rooms, 0)
    const totalArea = projects.reduce((acc, p) => acc + p.total_area_m2, 0)
    return { totalFloors, totalRooms, totalArea }
  }, [projects])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = q
      ? projects.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            p.filename.toLowerCase().includes(q) ||
            (p.project_code || '').toLowerCase().includes(q),
        )
      : [...projects]

    if (sortBy === 'area') {
      list.sort((a, b) => b.total_area_m2 - a.total_area_m2)
    } else if (sortBy === 'name') {
      list.sort((a, b) => a.name.localeCompare(b.name))
    } else {
      list.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      )
    }
    return list
  }, [projects, query, sortBy])

  const submitRename = async (id: string) => {
    if (!draftName.trim()) return
    await onRenameProject(id, draftName.trim())
    setEditingId(null)
  }

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Top Hero + Upload Dropzone */}
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const file = e.dataTransfer.files?.[0]
            if (file) onUploadPdf(file)
          }}
          className={`flex flex-col justify-between gap-4 rounded-2xl border-2 border-dashed bg-white p-6 shadow-sm transition md:flex-row md:items-center ${
            dragOver ? 'border-sky-500 bg-sky-50/40' : 'border-slate-200'
          }`}
        >
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600">
              <FileUp className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900">
                Tạo dự án mới từ bản vẽ PDF
              </h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Kéo thả file PDF mặt bằng vào đây để tự động bóc tách tường, cửa, đa giác phòng và xuất AutoCAD (.DXF) + 3D.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100">
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(e) => onToggleLlm(e.target.checked)}
                className="accent-sky-600"
              />
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              Gemini Vision
            </label>

            <label className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-sky-500">
              <FileUp className="h-3.5 w-3.5" />
              Chọn file PDF
              <input
                type="file"
                accept=".pdf,application/pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) onUploadPdf(f)
                  e.target.value = ''
                }}
              />
            </label>
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-medium text-slate-500">Tổng dự án</div>
            <div className="mt-1 text-2xl font-bold text-slate-900">{projects.length}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-medium text-slate-500">Mặt bằng tầng</div>
            <div className="mt-1 text-2xl font-bold text-sky-700">{stats.totalFloors}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-medium text-slate-500">Phòng đã tách</div>
            <div className="mt-1 text-2xl font-bold text-emerald-700">{stats.totalRooms}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-medium text-slate-500">Tổng diện tích</div>
            <div className="mt-1 text-2xl font-bold text-slate-900">
              {stats.totalArea.toFixed(1)}{' '}
              <span className="text-sm font-normal text-slate-500">m²</span>
            </div>
          </div>
        </div>

        {/* Search & Filter */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Tìm dự án theo tên, mã dự án hoặc tên file PDF..."
              className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-xs text-slate-800 shadow-sm outline-none focus:border-sky-500"
            />
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-600">
            <span>Sắp xếp:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortKey)}
              className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-medium text-slate-700 shadow-sm outline-none focus:border-sky-500"
            >
              <option value="newest">Mới nhất</option>
              <option value="area">Diện tích lớn nhất</option>
              <option value="name">Tên A → Z</option>
            </select>
          </div>
        </div>

        {/* Project Cards Grid */}
        {filtered.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center shadow-sm">
            <FolderOpen className="mx-auto mb-3 h-10 w-10 text-slate-300" />
            <p className="text-sm font-medium text-slate-700">
              {projects.length === 0
                ? 'Chưa có dự án nào được lưu'
                : 'Không tìm thấy dự án phù hợp'}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              Hãy kéo thả hoặc chọn file PDF mặt bằng để bắt đầu dự án mới.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => {
              const isEditing = editingId === p.id
              const isConfirmDel = confirmDeleteId === p.id
              return (
                <div
                  key={p.id}
                  className="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-300 hover:shadow-md"
                >
                  <div>
                    {/* Title Row */}
                    <div className="flex items-start justify-between gap-2">
                      {isEditing ? (
                        <div className="flex flex-1 items-center gap-1">
                          <input
                            type="text"
                            value={draftName}
                            onChange={(e) => setDraftName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') submitRename(p.id)
                              if (e.key === 'Escape') setEditingId(null)
                            }}
                            autoFocus
                            className="w-full rounded-md border border-sky-400 px-2 py-1 text-xs font-semibold text-slate-900 outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => submitRename(p.id)}
                            className="rounded p-1 text-emerald-600 hover:bg-emerald-50"
                            title="Lưu"
                          >
                            <Check className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingId(null)}
                            className="rounded p-1 text-slate-400 hover:bg-slate-100"
                            title="Hủy"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => onOpenProject(p.id)}
                            className="text-left text-sm font-semibold text-slate-900 hover:text-sky-700"
                          >
                            {p.name}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setEditingId(p.id)
                              setDraftName(p.name)
                            }}
                            className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                            title="Đổi tên dự án"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>

                    {/* Sub-info */}
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                      <span className="inline-flex items-center gap-1">
                        <FileText className="h-3 w-3" /> {p.filename}
                      </span>
                      <span>·</span>
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-700">
                        {p.scale_ratio}
                      </span>
                      {p.project_code && (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600">
                          #{p.project_code}
                        </span>
                      )}
                      {p.use_llm && (
                        <span className="inline-flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">
                          <Sparkles className="h-2.5 w-2.5" /> AI
                        </span>
                      )}
                    </div>

                    {/* Metrics */}
                    <div className="mt-3 grid grid-cols-4 gap-1.5 rounded-xl bg-slate-50 p-2.5 text-center">
                      <div>
                        <div className="text-xs font-semibold text-slate-900">
                          {p.floors_count}
                        </div>
                        <div className="text-[10px] text-slate-500">Tầng</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-slate-900">
                          {p.total_walls}
                        </div>
                        <div className="text-[10px] text-slate-500">Tường</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-sky-700">
                          {p.total_rooms}
                        </div>
                        <div className="text-[10px] text-slate-500">Phòng</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-emerald-700">
                          {p.total_area_m2.toFixed(0)} m²
                        </div>
                        <div className="text-[10px] text-slate-500">Diện tích</div>
                      </div>
                    </div>
                  </div>

                  {/* Footer Actions */}
                  <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3">
                    <span className="text-[11px] text-slate-400">
                      {new Date(p.updated_at).toLocaleString('vi-VN', {
                        dateStyle: 'short',
                        timeStyle: 'short',
                      })}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {isConfirmDel ? (
                        <>
                          <button
                            type="button"
                            onClick={async () => {
                              await onDeleteProject(p.id)
                              setConfirmDeleteId(null)
                            }}
                            className="rounded-md bg-rose-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-rose-500"
                          >
                            Xóa
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(null)}
                            className="rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
                          >
                            Hủy
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => setConfirmDeleteId(p.id)}
                            className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                            title="Xóa dự án"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                          <a
                            href={`/api/jobs/${p.id}/download/dxf`}
                            download
                            className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50"
                            title="Tải nhanh DXF"
                          >
                            <Download className="h-3.5 w-3.5" />
                          </a>
                          <button
                            type="button"
                            onClick={() => onOpenProject(p.id)}
                            className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-sky-700"
                          >
                            <Layers className="h-3 w-3" /> Mở Studio
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
