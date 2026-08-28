import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any

import docker
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from analyzer import DiagnosticAnalyzer

load_dotenv()


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, event: dict[str, Any]):
        disconnected = []
        for websocket in self.connections:
            try:
                await websocket.send_json(event)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)


manager = ConnectionManager()
docker_client = docker.from_env()
analyzer = DiagnosticAnalyzer(
    os.getenv("PROMETHEUS_URL", "http://prometheus:9090"), docker_client
)
poller_task: asyncio.Task | None = None
last_anomaly_signature: str | None = None
latest_incident: dict[str, Any] | None = None


async def anomaly_poller():
    global last_anomaly_signature, latest_incident
    while True:
        try:
            metrics = await asyncio.to_thread(analyzer.collect_metrics)
            services = await asyncio.to_thread(analyzer.collect_service_status)
            await manager.broadcast({"type": "health", "metrics": metrics, "services": services})
            anomaly = analyzer.anomaly_from_metrics(metrics, services)
            signature = str(anomaly["reasons"]) if anomaly else None
            if anomaly and signature != last_anomaly_signature:
                last_anomaly_signature = signature
                logs = await asyncio.to_thread(analyzer.collect_logs)
                report = await asyncio.to_thread(analyzer.diagnose, anomaly, logs)
                latest_incident = {
                    "report": report.model_dump(),
                    "anomaly": anomaly,
                    "logs": logs,
                    "metrics": metrics,
                    "services": services,
                }
                await manager.broadcast(
                    {
                        "type": "incident",
                        "report": latest_incident["report"],
                        "anomaly": anomaly,
                        "logs": logs,
                        "metrics": metrics,
                        "services": services,
                    }
                )
            elif not anomaly:
                last_anomaly_signature = None
        except Exception as error:
            print(f"Anomaly poll failed: {error}")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global poller_task
    poller_task = asyncio.create_task(anomaly_poller())
    yield
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Resilio AI Diagnostic Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "ai-engine", "websocket_clients": len(manager.connections)}


@app.get("/")
def service_info():
    return {"service": "ai-engine", "status": "ok", "health": "/health", "incidents": "/api/incidents/latest"}


@app.get("/metrics/current")
def current_metrics():
    metrics = analyzer.collect_metrics()
    services = analyzer.collect_service_status()
    return {
        "metrics": metrics,
        "services": services,
        "anomaly": analyzer.anomaly_from_metrics(metrics, services),
    }


@app.get("/api/incidents/latest")
def latest_incident_report():
    if latest_incident is None:
        return {"incident": None}
    return latest_incident


@app.post("/api/chat")
async def query_ai(request: ChatRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    metrics = analyzer.collect_metrics()
    services = analyzer.collect_service_status()
    logs = analyzer.collect_logs()
    anomaly = analyzer.anomaly_from_metrics(metrics, services)

    prompt = (
        "You are Resilio's senior site reliability engineer and AI operations copilot. "
        "Answer the user's question using the live system state below. "
        "Be precise, technical, and concise. Use the current metrics and logs as the source of truth.\n\n"
        f"User question: {query}\n\n"
        f"Current service status: {json.dumps(services, indent=2, default=str)}\n\n"
        f"Current metrics: {json.dumps(metrics, indent=2, default=str)}\n\n"
        f"Detected anomaly: {json.dumps(anomaly, indent=2, default=str) if anomaly else 'None'}\n\n"
        f"Latest logs: {json.dumps({k: v[-2000:] for k, v in logs.items()}, indent=2, default=str)}"
    )

    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_api_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_api_key)
            response = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
                contents=prompt,
                config={"response_mime_type": "text/plain"},
            )
            return {"answer": response.text.strip()}
        except Exception as error:
            print(f"Gemini chat failed, using fallback: {error}")

    return {
        "answer": (
            f"Based on the live telemetry, the system is currently in {anomaly['reasons'] if anomaly else 'stable'} "
            f"state. Service health is {services}. "
            f"Latency metrics: {json.dumps(metrics, default=str)}. "
            f"The available logs indicate recent container behavior. "
            f"For a more specific diagnosis, ask about a specific service, error rate, or failure pattern."
        )
    }


@app.websocket("/ws/incidents")
async def incident_stream(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_json({"type": "connected", "service": "ai-engine"})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
