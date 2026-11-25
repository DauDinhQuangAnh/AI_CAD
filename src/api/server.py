"""FastAPI server exposing AI_CAD 5-stage pipeline, project management, and downloads."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src import __version__
from src.api.project_store import ProjectStore
from src.pipeline import AICADPipeline

logger = logging.getLogger(__name__)

JOBS_ROOT = Path("data/outputs/jobs")
SAMPLE_PDF = Path("data/raw/test1.pdf")
_JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")

store = ProjectStore()

app = FastAPI(
    title="AI_CAD API",
    version=__version__,
    description="Architectural Floor Plan Analysis & Vector CAD Generation API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RenameProjectRequest(BaseModel):
    name: str


@app.get("/api/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "version": __version__}


@app.get("/api/projects")
def list_projects() -> dict:
    """List all saved projects ordered by most recently updated."""
    projects = store.list_projects()
    return {"projects": [p.model_dump(mode="json") for p in projects]}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    """Load a saved project's full CAD document and download links."""
    try:
        data = store.get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return data


@app.patch("/api/projects/{project_id}")
def rename_project(project_id: str, body: RenameProjectRequest) -> dict:
    """Rename a saved project."""
    try:
        updated = store.rename_project(project_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project": updated.model_dump(mode="json")}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Delete a saved project and its generated outputs."""
    try:
        deleted = store.delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"deleted": True, "project_id": project_id}


def _run_job(pdf_path: Path, stem: str, use_llm: bool) -> dict:
    job_id = uuid.uuid4().hex[:12]
    job_dir = store.project_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    pipeline = AICADPipeline(use_llm=use_llm)
    outputs = pipeline.run(pdf_path, output_dir=job_dir, stem=stem)
    summary = store.register_project(
        project_id=job_id,
        filename=pdf_path.name,
        document=outputs.document,
        use_llm=use_llm,
    )

    return {
        "job_id": job_id,
        "project": summary.model_dump(mode="json"),
        "filename": pdf_path.name,
        "document": outputs.document.model_dump(mode="json"),
        "downloads": {
            "dxf": f"/api/jobs/{job_id}/download/dxf",
            "floorplanner": f"/api/jobs/{job_id}/download/floorplanner",
            "schema": f"/api/jobs/{job_id}/download/schema",
        },
    }


@app.post("/api/analyze")
async def analyze_pdf(
    file: UploadFile = File(...),
    use_llm: bool = Form(False),
) -> dict:
    """Upload a vector PDF floor plan, run the AI_CAD pipeline, and save as a project."""
    filename = file.filename or "floorplan.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = store.project_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(filename).stem) or "floorplan"
    input_pdf = job_dir / f"{safe_stem}.pdf"

    with input_pdf.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        pipeline = AICADPipeline(use_llm=use_llm)
        outputs = pipeline.run(input_pdf, output_dir=job_dir, stem=safe_stem)
        summary = store.register_project(
            project_id=job_id,
            filename=filename,
            document=outputs.document,
            use_llm=use_llm,
        )
    except Exception as exc:
        logger.exception("Pipeline failed for %s", filename)
        raise HTTPException(status_code=500, detail=f"Pipeline processing failed: {exc}") from exc

    return {
        "job_id": job_id,
        "project": summary.model_dump(mode="json"),
        "filename": filename,
        "document": outputs.document.model_dump(mode="json"),
        "downloads": {
            "dxf": f"/api/jobs/{job_id}/download/dxf",
            "floorplanner": f"/api/jobs/{job_id}/download/floorplanner",
            "schema": f"/api/jobs/{job_id}/download/schema",
        },
    }


@app.post("/api/analyze-sample")
def analyze_sample(use_llm: bool = False) -> dict:
    """Run the pipeline on the built-in sample PDF (data/raw/test1.pdf) and save as a project."""
    if not SAMPLE_PDF.exists():
        raise HTTPException(status_code=404, detail="Sample PDF data/raw/test1.pdf not found.")
    return _run_job(SAMPLE_PDF, stem="test1", use_llm=use_llm)


@app.get("/api/jobs/{job_id}/download/{kind}")
def download_output(
    job_id: str,
    kind: Literal["dxf", "floorplanner", "schema"],
) -> FileResponse:
    """Download generated DXF, Floorplanner JSON, or Unified Schema JSON."""
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id.")

    job_dir = store.project_dir(job_id)
    if not job_dir.exists():
        job_dir = JOBS_ROOT / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    suffix_map = {
        "dxf": "*.dxf",
        "floorplanner": "*_floorplanner.json",
        "schema": "*_schema.json",
    }
    matches = list(job_dir.glob(suffix_map[kind]))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Output '{kind}' not found for job {job_id}.")

    target = matches[0]
    media_type = "application/dxf" if kind == "dxf" else "application/json"
    return FileResponse(path=target, filename=target.name, media_type=media_type)
