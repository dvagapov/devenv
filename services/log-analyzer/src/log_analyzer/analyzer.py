from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any

from .clickhouse_store import ClickHouseStore
from .config import Settings
from .llm_client import generate_summary


class AnalyzerService:
    STEPS = (
        "aggregation",
        "anomaly_detection",
        "prompt_build",
        "llm_call",
        "store_result",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = ClickHouseStore(settings)

    def run_once(self, now: datetime | None = None) -> dict[str, Any]:
        self.store.ensure_tables()

        now_dt = (now or datetime.utcnow()).replace(second=0, microsecond=0)
        window_end = now_dt.replace(minute=0)
        window_start = window_end - timedelta(minutes=self.settings.analyzer_window_minutes)

        run_id = f"{self.settings.analyzer_job_id}:{window_end.strftime('%Y%m%d%H%M')}"
        job_id = self.settings.analyzer_job_id

        context: dict[str, Any] = {
            "job_id": job_id,
            "run_id": run_id,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }

        for step in self.STEPS:
            checkpoint = self.store.get_step_checkpoint(job_id, run_id, step)
            if checkpoint is not None:
                context[step] = checkpoint
                continue

            self.store.upsert_step(job_id, run_id, step, "in_progress", {"context_keys": list(context.keys())})
            try:
                result = self._run_step(step, context, window_start, window_end)
            except Exception as exc:
                self.store.upsert_step(
                    job_id,
                    run_id,
                    step,
                    "failed",
                    {"error": str(exc), "failed_at": datetime.utcnow().isoformat()},
                )
                raise

            self.store.upsert_step(job_id, run_id, step, "completed", result)
            context[step] = result

        return {
            "job_id": job_id,
            "run_id": run_id,
            "status": "completed",
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }

    def _run_step(
        self,
        step: str,
        context: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, Any]:
        if step == "aggregation":
            return self._step_aggregation(window_start, window_end)
        if step == "anomaly_detection":
            return self._step_anomaly_detection(context, window_start)
        if step == "prompt_build":
            return self._step_prompt_build(context)
        if step == "llm_call":
            return self._step_llm_call(context)
        if step == "store_result":
            return self._step_store_result(context, window_start, window_end)
        raise ValueError(f"Unknown step: {step}")

    def _step_aggregation(self, window_start: datetime, window_end: datetime) -> dict[str, Any]:
        service_column = self.store.detect_service_column()
        log_counts = self.store.query_log_counts(service_column, window_start, window_end)
        metric_summary = self.store.query_metric_summary(window_start, window_end)

        return {
            "service_column": service_column,
            "log_counts": log_counts,
            "metric_summary": metric_summary,
            "log_services": len(log_counts),
            "metric_series": len(metric_summary),
        }

    def _step_anomaly_detection(self, context: dict[str, Any], window_start: datetime) -> dict[str, Any]:
        aggregation = context["aggregation"]
        service_column = aggregation["service_column"]
        baseline_start = window_start - timedelta(hours=24)

        baseline_rows = self.store.query_log_baseline(
            service_col=service_column,
            baseline_start=baseline_start,
            window_start=window_start,
            window_minutes=self.settings.analyzer_window_minutes,
        )

        baseline_by_service = {row["service_name"]: row for row in baseline_rows}

        anomalies: list[dict[str, Any]] = []
        for row in aggregation["log_counts"]:
            service_name = row["service_name"]
            current_count = float(row["log_count"])
            baseline = baseline_by_service.get(service_name)
            if not baseline:
                continue
            avg_val = float(baseline["baseline_avg"] or 0.0)
            std_val = float(baseline["baseline_std"] or 0.0)
            points = int(baseline["baseline_points"] or 0)

            if points < 5 or std_val <= 0:
                continue

            zscore = (current_count - avg_val) / std_val
            if math.fabs(zscore) >= self.settings.anomaly_zscore_threshold:
                anomalies.append(
                    {
                        "service_name": service_name,
                        "signal_type": "log_volume",
                        "current_value": current_count,
                        "baseline_avg": avg_val,
                        "baseline_std": std_val,
                        "baseline_points": points,
                        "zscore": round(zscore, 3),
                    }
                )

        anomalies.sort(key=lambda x: abs(x["zscore"]), reverse=True)
        return {
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
        }

    def _step_prompt_build(self, context: dict[str, Any]) -> dict[str, Any]:
        aggregation = context["aggregation"]
        anomaly_detection = context["anomaly_detection"]

        top_services = aggregation["log_counts"][:15]
        top_metrics = aggregation["metric_summary"][:20]
        anomalies = anomaly_detection["anomalies"][:20]

        prompt = (
            "You are an SRE assistant. Analyze Kubernetes telemetry and provide concise system health summary.\\n"
            "Return sections: overall_status, key_findings, anomalous_services, recommended_actions.\\n"
            f"Window: {context['window_start']} to {context['window_end']} UTC\\n\\n"
            f"Top services by log volume: {json.dumps(top_services, ensure_ascii=True)}\\n\\n"
            f"Metric summary: {json.dumps(top_metrics, ensure_ascii=True)}\\n\\n"
            f"Detected anomalies: {json.dumps(anomalies, ensure_ascii=True)}\\n"
        )

        return {
            "prompt": prompt,
            "top_services": top_services,
            "top_metrics": top_metrics,
            "anomaly_count": anomaly_detection["anomaly_count"],
        }

    def _step_llm_call(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = context["prompt_build"]["prompt"]
        summary, model = generate_summary(self.settings, prompt)
        return {
            "summary": summary,
            "model": model,
        }

    def _step_store_result(
        self,
        context: dict[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, Any]:
        job_id = context["job_id"]
        run_id = context["run_id"]
        summary = context["llm_call"]["summary"]
        model = context["llm_call"]["model"]
        anomalies = context["anomaly_detection"]["anomalies"]
        metrics = context["aggregation"]["metric_summary"]
        prompt = context["prompt_build"]["prompt"]

        self.store.insert_report(
            job_id=job_id,
            run_id=run_id,
            window_start=window_start,
            window_end=window_end,
            status="completed",
            summary=summary,
            prompt=prompt,
            model=model,
            anomalies_json=json.dumps(anomalies, ensure_ascii=True),
            metrics_json=json.dumps(metrics[:100], ensure_ascii=True),
        )

        knowledge_rows = self._build_knowledge_rows(job_id, run_id, anomalies)
        self.store.insert_knowledge(knowledge_rows)

        return {
            "report_saved": True,
            "knowledge_rows": len(knowledge_rows),
            "saved_at": datetime.utcnow().isoformat(),
        }

    def _build_knowledge_rows(
        self, job_id: str, run_id: str, anomalies: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now = datetime.utcnow().replace(microsecond=0)
        rows: list[dict[str, Any]] = []
        for item in anomalies[:50]:
            service_name = item.get("service_name", "unknown")
            zscore = float(item.get("zscore", 0.0))
            direction = "spike" if zscore > 0 else "drop"
            rows.append(
                {
                    "job_id": job_id,
                    "run_id": run_id,
                    "service_name": service_name,
                    "signal_type": item.get("signal_type", "log_volume"),
                    "insight": f"{service_name} log volume {direction} detected (zscore={zscore:.2f})",
                    "confidence": min(1.0, abs(zscore) / 10.0),
                    "created_at": now,
                }
            )
        return rows
