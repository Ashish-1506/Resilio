import json
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import docker
import requests
from google import genai
from pydantic import BaseModel, Field


class IncidentReport(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    root_cause_service: str
    failure_mode: str
    confidence_score: str
    diagnosis_source: str
    impact_summary: str
    recommended_remediation: str


class DiagnosticAnalyzer:
    def __init__(self, prometheus_url: str, docker_client: docker.DockerClient):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.docker_client = docker_client
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    def query_prometheus(self, query: str) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.prometheus_url}/api/v1/query",
            params={"query": query},
            timeout=4,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            return []
        return payload.get("data", {}).get("result", [])

    def collect_metrics(self) -> dict[str, Any]:
        error_query = (
            "sum(rate(http_server_request_duration_seconds_count"
            "{http_response_status_code=~\"5..\"}[1m])) / "
            "clamp_min(sum(rate(http_server_request_duration_seconds_count[1m])), 0.001)"
        )
        latency_query = (
            "histogram_quantile(0.95, sum(rate(" 
            "http_server_request_duration_seconds_bucket[1m])) by (le))"
        )
        metrics = {"error_rate": [], "latency_p95": []}
        try:
            metrics["error_rate"] = self._finite_results(self.query_prometheus(error_query))
            metrics["latency_p95"] = self._finite_results(self.query_prometheus(latency_query))
        except requests.RequestException as error:
            metrics["error"] = str(error)
        return metrics

    def anomaly_from_metrics(
        self, metrics: dict[str, Any], services: dict[str, str] | None = None
    ) -> dict[str, Any] | None:
        error_value = self._first_value(metrics.get("error_rate", []))
        latency_value = self._first_value(metrics.get("latency_p95", []))
        unavailable = {
            name: status
            for name, status in (services or {}).items()
            if status != "running"
        }
        if error_value <= 0.05 and latency_value <= 0.4 and not unavailable:
            return None

        reasons = []
        if error_value > 0.05:
            reasons.append(f"5xx rate is {error_value:.2%}")
        if latency_value > 0.4:
            reasons.append(f"p95 latency is {latency_value * 1000:.0f}ms")
        if unavailable:
            reasons.append(
                "service state: "
                + ", ".join(f"{name}={status}" for name, status in unavailable.items())
            )
        return {
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "reasons": reasons,
            "error_rate": error_value,
            "latency_p95_seconds": latency_value,
            "services": services or {},
            "metrics": metrics,
        }

    def collect_logs(self) -> dict[str, str]:
        logs: dict[str, str] = {}
        for container in self.docker_client.containers.list():
            try:
                raw_logs = container.logs(tail=50, timestamps=True)
                logs[container.name] = raw_logs.decode("utf-8", errors="replace")
            except docker.errors.DockerException as error:
                logs[container.name] = f"Unable to read logs: {error}"
        return logs

    def collect_service_status(self) -> dict[str, str]:
        statuses = {}
        for container_name in ("resilio-gateway", "resilio-order-service", "resilio-postgres"):
            try:
                container = self.docker_client.containers.get(container_name)
                status = container.status
                if status == "running" and container.attrs.get("State", {}).get("Paused"):
                    status = "paused"
                statuses[container_name] = status
            except docker.errors.DockerException:
                statuses[container_name] = "unavailable"
        return statuses

    def diagnose(self, anomaly: dict[str, Any], logs: dict[str, str]) -> IncidentReport:
        prompt = self._build_prompt(anomaly, logs)
        if self.gemini_api_key:
            try:
                client = genai.Client(api_key=self.gemini_api_key)
                response = client.models.generate_content(
                    model=self.gemini_model,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                report = IncidentReport.model_validate_json(response.text)
                return report.model_copy(update={"diagnosis_source": "Live Gemini Analysis"})
            except Exception as error:
                print(f"Gemini diagnosis failed, using local fallback: {error}")

        return self._fallback_report(anomaly, logs)

    def _build_prompt(self, anomaly: dict[str, Any], logs: dict[str, str]) -> str:
        return (
            "You are Resilio's production incident diagnostician. Return only valid JSON "
            "matching this schema: incident_id (UUID string), root_cause_service (string), "
            "failure_mode (string), confidence_score (percentage string), impact_summary "
            "(string), recommended_remediation (concrete CLI or code fix string), "
            "diagnosis_source (exactly 'Live Gemini Analysis').\n\n"
            f"Anomaly:\n{json.dumps(anomaly, indent=2)}\n\n"
            f"Last 50 log lines per active container:\n{json.dumps(logs, indent=2)}"
        )

    def _fallback_report(self, anomaly: dict[str, Any], logs: dict[str, str]) -> IncidentReport:
        root_service = "resilio-order-service" if anomaly["error_rate"] > 0.05 else "resilio-gateway"
        mode = "Service Unresponsive" if anomaly["error_rate"] > 0.05 else "High Latency"
        return IncidentReport(
            root_cause_service=root_service,
            failure_mode=mode,
            confidence_score=calculate_heuristic_score(anomaly.get("metrics", {}), logs),
            diagnosis_source="Local Heuristic Analysis",
            impact_summary=(
                f"Anomaly detected: {', '.join(anomaly['reasons'])}. "
                f"Correlated logs were collected from {len(logs)} active containers."
            ),
            recommended_remediation=(
                "Inspect the correlated container logs, verify the downstream database health, "
                "and roll back or restart the affected service if the error rate persists."
            ),
        )

    @staticmethod
    def _first_value(results: list[dict[str, Any]]) -> float:
        if not results:
            return 0.0
        try:
            value = float(results[0]["value"][1])
            return value if math.isfinite(value) else 0.0
        except (KeyError, IndexError, TypeError, ValueError):
            return 0.0

    @staticmethod
    def _finite_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            result
            for result in results
            if len(result.get("value", [])) > 1
            and math.isfinite(float(result["value"][1]))
        ]


def calculate_heuristic_score(metrics: dict[str, Any], logs: dict[str, str]) -> str:
    """Score the fallback diagnosis from correlated telemetry evidence."""
    latency_results = metrics.get("latency_p95", [])
    error_results = metrics.get("error_rate", [])
    latency_value = DiagnosticAnalyzer._first_value(latency_results)
    error_value = DiagnosticAnalyzer._first_value(error_results)
    latency_services = _metric_service_names(latency_results)
    error_services = _metric_service_names(error_results)

    if latency_value > 0.4 and error_value > 0.05:
        shared_services = latency_services & error_services
        if shared_services and any(service in logs for service in shared_services):
            return "90%"
        if shared_services:
            return "90%"
    if latency_value > 0.4 or error_value > 0.05:
        return "80%"
    return "65%"


def _metric_service_names(results: list[dict[str, Any]]) -> set[str]:
    service_keys = ("service_name", "service", "job", "container")
    names = set()
    for result in results:
        labels = result.get("metric", {})
        names.update(str(labels[key]) for key in service_keys if labels.get(key))
    return names
