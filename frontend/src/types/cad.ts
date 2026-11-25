export interface Point2D {
  x: number
  y: number
}

export interface BoundingBox {
  x_min: number
  y_min: number
  x_max: number
  y_max: number
}

export interface Corner {
  id: string
  x: number
  y: number
  elevation: number
}

export interface Wall {
  id: string
  corner_start_id: string
  corner_end_id: string
  wall_type: 'exterior' | 'interior' | 'bearing'
  thickness: number
  height: number
}

export interface Opening {
  id: string
  type: 'swing_door' | 'sliding_door' | 'window' | 'opening'
  wall_id: string
  position_along_wall_mm: number
  width: number
  height: number
}

export interface Space {
  id: string
  name: string
  name_vn?: string | null
  category: string
  nominal_area_m2?: number | null
  calculated_area_m2?: number | null
  boundary_corner_ids: string[]
  area_error_pct?: number | null
}

export interface Dimension {
  id: string
  text: string
  value_mm: number
  orientation: 'horizontal' | 'vertical' | 'diagonal'
  start_point: Point2D
  end_point: Point2D
}

export interface FloorPlan {
  floor_id: string
  floor_name: string
  elevation_peil?: number | null
  bounding_box: BoundingBox
  corners: Corner[]
  walls: Wall[]
  openings: Opening[]
  spaces: Space[]
  dimensions?: Dimension[]
}

export interface ProjectMetadata {
  project_name: string
  project_code?: string | null
  address?: string | null
  scale_ratio: string
  units: string
}

export interface AICADDocument {
  project_metadata: ProjectMetadata
  floors: FloorPlan[]
}

export interface ProjectSummary {
  id: string
  name: string
  filename: string
  project_code?: string | null
  scale_ratio: string
  floors_count: number
  total_walls: number
  total_openings: number
  total_rooms: number
  total_area_m2: number
  use_llm: boolean
  created_at: string
  updated_at: string
}

export interface AnalyzeResponse {
  job_id: string
  project?: ProjectSummary
  filename: string
  document: AICADDocument
  downloads: {
    dxf: string
    floorplanner: string
    schema: string
  }
}
