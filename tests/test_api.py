"""API integration tests for FastAPI server and Project Management CRUD."""

from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_analyze_sample_and_project_crud():
    res = client.post("/api/analyze-sample")
    assert res.status_code == 200
    data = res.json()
    pid = data["job_id"]
    assert len(data["document"]["floors"]) == 2

    # Download DXF
    dxf_res = client.get(data["downloads"]["dxf"])
    assert dxf_res.status_code == 200
    assert len(dxf_res.content) > 1000

    # List projects contains new project
    list_res = client.get("/api/projects")
    assert list_res.status_code == 200
    ids = [p["id"] for p in list_res.json()["projects"]]
    assert pid in ids

    # Get project
    get_res = client.get(f"/api/projects/{pid}")
    assert get_res.status_code == 200
    assert get_res.json()["job_id"] == pid

    # Rename project
    ren_res = client.patch(f"/api/projects/{pid}", json={"name": "Renamed Test Project"})
    assert ren_res.status_code == 200
    assert ren_res.json()["project"]["name"] == "Renamed Test Project"

    # Delete project
    del_res = client.delete(f"/api/projects/{pid}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Confirm deleted
    assert client.get(f"/api/projects/{pid}").status_code == 404
