"""Nightly reporting script for our Langfuse project.

Pulls traces and scores and writes a CSV summary. This is existing code that predates
the v4 API changes — it still uses the older read endpoints.
"""
import csv
import os

from langfuse import Langfuse

lf = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
    host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
)


def recent_traces(limit: int = 100):
    # GET /api/public/traces
    return lf.api.trace.list(limit=limit).data


def scores_for_trace(trace_id: str):
    # GET /api/public/v2/scores?traceId=...
    return lf.api.score.get_many(trace_id=trace_id).data


def build_report(path: str = "report.csv"):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["trace_id", "name", "latency_ms", "score_name", "score_value"])
        for trace in recent_traces():
            for score in scores_for_trace(trace.id):
                writer.writerow(
                    [trace.id, trace.name, trace.latency, score.name, score.value]
                )


if __name__ == "__main__":
    build_report()
