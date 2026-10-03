from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import run_agent

app = FastAPI(title="PortfolioAgent")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
GENERATED_SITES_DIR = PROJECT_ROOT / "generated-sites"
jobs: dict[str, dict] = {}
jobs_lock = Lock()


class PortfolioRequest(BaseModel):
    prompt: str = Field(min_length=1)


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIR),
    name="frontend-assets",
)
app.mount(
    "/sites",
    StaticFiles(directory=GENERATED_SITES_DIR, html=True),
    name="generated-sites",
)


def _run_job(job_id: str, prompt: str) -> None:
    def publish(event: dict) -> None:
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job["events"].append(event)
                if event.get("project_name"):
                    job["project_name"] = event["project_name"]

    try:
        result = run_agent(prompt, on_event=publish)
        lines = result.splitlines()
        project_name = None
        files = []
        for index, line in enumerate(lines):
            if line.startswith("Project: "):
                project_name = line.removeprefix("Project: ").strip()
            elif line == "Files:":
                files = [
                    item.removeprefix("- ").strip()
                    for item in lines[index + 1:]
                    if item.startswith("- ")
                ]

        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "completed",
                    "message": result,
                    "project_name": project_name or jobs[job_id]["project_name"],
                    "files": files,
                }
            )
    except HTTPException as exc:
        detail = (
            exc.detail
            if isinstance(exc.detail, str)
            else "Website generation failed."
        )
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "failed",
                    "error": detail,
                }
            )
            jobs[job_id]["events"].append(
                {
                    "state": "failed",
                    "message": detail,
                    "project_name": jobs[job_id]["project_name"],
                }
            )
    except Exception:
        with jobs_lock:
            jobs[job_id].update(
                {
                    "status": "failed",
                    "error": "Website generation failed unexpectedly.",
                }
            )
            jobs[job_id]["events"].append(
                {
                    "state": "failed",
                    "message": "Website generation failed unexpectedly.",
                    "project_name": jobs[job_id]["project_name"],
                }
            )


@app.post("/portfolio")
def portfolio(request: PortfolioRequest, background_tasks: BackgroundTasks):
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt must not be empty.")

    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "events": [
                {
                    "state": "accepted",
                    "message": "Backend accepted the website build request.",
                    "project_name": None,
                }
            ],
            "project_name": None,
            "files": [],
        }
    background_tasks.add_task(_run_job, job_id, prompt)
    return {"job_id": job_id, "status": "running"}


@app.get("/portfolio/{job_id}")
def portfolio_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Build job not found.")
        return {
            **job,
            "events": list(job["events"]),
            "files": list(job["files"]),
        }
