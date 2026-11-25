"""Persistent file-backed Project Store for AI_CAD Studio."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.core.schema import AICADDocument

_PROJECT_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class ProjectSummary(BaseModel):
    """Lightweight summary stored in the projects index."""

    id: str
    name: str
    filename: str
    project_code: Optional[str] = None
    scale_ratio: str = "1:100"
    floors_count: int = 0
    total_walls: int = 0
    total_openings: int = 0
    total_rooms: int = 0
    total_area_m2: float = 0.0
    use_llm: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectStore:
    """Manages saved AI_CAD projects on disk."""

    def __init__(self, root_dir: str | Path = "data/outputs/projects") -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root_dir / "projects.json"

    def _load_index(self) -> list[ProjectSummary]:
        if not self.index_path.exists():
            return []
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            return [ProjectSummary.model_validate(item) for item in raw]
        except Exception:
            return []

    def _save_index(self, items: list[ProjectSummary]) -> None:
        payload = [item.model_dump(mode="json") for item in items]
        self.index_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def validate_id(project_id: str) -> None:
        if not _PROJECT_ID_RE.match(project_id):
            raise ValueError(f"Invalid project_id: {project_id}")

    def project_dir(self, project_id: str) -> Path:
        self.validate_id(project_id)
        return self.root_dir / project_id

    def list_projects(self) -> list[ProjectSummary]:
        items = self._load_index()
        items.sort(key=lambda p: p.updated_at, reverse=True)
        return items

    def register_project(
        self,
        project_id: str,
        filename: str,
        document: AICADDocument,
        use_llm: bool = False,
    ) -> ProjectSummary:
        self.validate_id(project_id)
        now = datetime.now(timezone.utc)
        total_walls = sum(len(f.walls) for f in document.floors)
        total_openings = sum(len(f.openings) for f in document.floors)
        total_rooms = sum(len(f.spaces) for f in document.floors)
        total_area = round(
            sum(
                sp.calculated_area_m2 or 0.0
                for f in document.floors
                for sp in f.spaces
            ),
            2,
        )

        summary = ProjectSummary(
            id=project_id,
            name=document.project_metadata.project_name or Path(filename).stem,
            filename=filename,
            project_code=document.project_metadata.project_code,
            scale_ratio=document.project_metadata.scale_ratio,
            floors_count=len(document.floors),
            total_walls=total_walls,
            total_openings=total_openings,
            total_rooms=total_rooms,
            total_area_m2=total_area,
            use_llm=use_llm,
            created_at=now,
            updated_at=now,
        )

        items = [p for p in self._load_index() if p.id != project_id]
        items.insert(0, summary)
        self._save_index(items)
        return summary

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        self.validate_id(project_id)
        items = self._load_index()
        summary = next((p for p in items if p.id == project_id), None)
        if summary is None:
            return None

        pdir = self.project_dir(project_id)
        schema_files = list(pdir.glob("*_schema.json"))
        if not schema_files:
            return None

        doc_data = json.loads(schema_files[0].read_text(encoding="utf-8"))
        return {
            "project": summary.model_dump(mode="json"),
            "job_id": project_id,
            "filename": summary.filename,
            "document": doc_data,
            "downloads": {
                "dxf": f"/api/jobs/{project_id}/download/dxf",
                "floorplanner": f"/api/jobs/{project_id}/download/floorplanner",
                "schema": f"/api/jobs/{project_id}/download/schema",
            },
        }

    def rename_project(self, project_id: str, new_name: str) -> Optional[ProjectSummary]:
        self.validate_id(project_id)
        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("Project name cannot be empty.")

        items = self._load_index()
        target: Optional[ProjectSummary] = None
        for p in items:
            if p.id == project_id:
                p.name = clean_name
                p.updated_at = datetime.now(timezone.utc)
                target = p
                break
        if target is None:
            return None

        # Also update project_name inside saved schema json
        pdir = self.project_dir(project_id)
        for sf in pdir.glob("*_schema.json"):
            data = json.loads(sf.read_text(encoding="utf-8"))
            if "project_metadata" in data:
                data["project_metadata"]["project_name"] = clean_name
                sf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        self._save_index(items)
        return target

    def delete_project(self, project_id: str) -> bool:
        self.validate_id(project_id)
        items = self._load_index()
        remaining = [p for p in items if p.id != project_id]
        if len(remaining) == len(items):
            return False
        self._save_index(remaining)
        pdir = self.project_dir(project_id)
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)
        return True
