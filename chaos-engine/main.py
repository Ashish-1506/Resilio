import asyncio

import docker
from docker.errors import APIError, DockerException, NotFound
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Resilio Chaos Engine", version="1.0.0")
docker_client = docker.from_env()


class ContainerRequest(BaseModel):
    container_name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.-]+$")


class FreezeRequest(ContainerRequest):
    duration: float = Field(gt=0, le=60)


def get_container(container_name: str):
    try:
        return docker_client.containers.get(container_name)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=f"Container not found: {container_name}") from error
    except DockerException as error:
        raise HTTPException(status_code=503, detail="Docker daemon is unavailable") from error


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "chaos-engine"}


@app.get("/")
def service_info():
    return {"service": "chaos-engine", "status": "ok", "health": "/health"}


@app.post("/chaos/crash")
async def crash_container(request: ContainerRequest):
    container = get_container(request.container_name)
    try:
        await asyncio.to_thread(container.kill, signal="SIGKILL")
        await asyncio.to_thread(container.start)
        return {
            "status": "restarted",
            "container_name": request.container_name,
        }
    except (APIError, DockerException) as error:
        raise HTTPException(status_code=502, detail="Unable to crash or restart container") from error


@app.post("/chaos/freeze")
async def freeze_container(request: FreezeRequest):
    container = get_container(request.container_name)
    try:
        await asyncio.to_thread(container.pause)
        try:
            await asyncio.sleep(request.duration)
        finally:
            await asyncio.to_thread(container.unpause)
        return {
            "status": "resumed",
            "container_name": request.container_name,
            "duration": request.duration,
        }
    except (APIError, DockerException) as error:
        raise HTTPException(status_code=502, detail="Unable to pause or resume container") from error


@app.post("/chaos/cpu-spike")
async def cpu_spike_container(request: ContainerRequest):
    container = get_container(request.container_name)
    command = (
        "cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1); "
        "for i in $(seq 1 $cores); do while :; do :; done & done; "
        "sleep 15; kill $(jobs -p) 2>/dev/null || true"
    )
    try:
        result = await asyncio.to_thread(container.exec_run, ["sh", "-c", command])
        if result.exit_code != 0:
            raise HTTPException(status_code=502, detail="CPU spike command failed")
        return {
            "status": "completed",
            "container_name": request.container_name,
            "duration": 15,
        }
    except HTTPException:
        raise
    except (APIError, DockerException) as error:
        raise HTTPException(status_code=502, detail="Unable to execute CPU spike") from error