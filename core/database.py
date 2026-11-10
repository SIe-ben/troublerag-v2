import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional


class TelemetryDB:
    """
    SQLite persistence layer for TroubleRAG:
      1. Logs every diagnostic query, latency, redaction count, and confidence score.
      2. Captures blocked/unknown errors in an Unresolved Incident Queue.
      3. Promotes human-verified resolutions directly into the Markdown runbook corpus.
    """

    def __init__(self, db_path: str = "data/incident_history.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Returns rows as dictionaries instead of tuples
        return conn

    def _init_tables(self) -> None:
        """Creates the telemetry and self-learning queue tables if they do not exist."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sanitized_query TEXT NOT NULL,
                    secrets_redacted INTEGER DEFAULT 0,
                    top_chunk_id TEXT,
                    vector_distance REAL,
                    bm25_score REAL,
                    confidence_pct REAL,
                    guardrail_status TEXT NOT NULL,
                    latency_ms REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS unresolved_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    sanitized_error_log TEXT NOT NULL,
                    highest_confidence_pct REAL,
                    status TEXT DEFAULT 'OPEN',
                    resolved_incident_id TEXT
                )
            """)
            conn.commit()

    def log_query_event(
        self,
        sanitized_query: str,
        secrets_redacted: int,
        top_chunk_id: str,
        vector_distance: float,
        bm25_score: float,
        confidence_pct: float,
        guardrail_passed: bool,
        latency_ms: float
    ) -> None:
        """Records a diagnostic run into query_telemetry and queues blocked queries."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_label = "PASSED" if guardrail_passed else "BLOCKED"

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO query_telemetry (
                    timestamp, sanitized_query, secrets_redacted, top_chunk_id,
                    vector_distance, bm25_score, confidence_pct, guardrail_status, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_str, sanitized_query, secrets_redacted, top_chunk_id,
                    vector_distance, bm25_score, confidence_pct, status_label, round(latency_ms, 1)
                )
            )

            # If blocked by guardrail, automatically add to the Unresolved Queue
            if not guardrail_passed:
                conn.execute(
                    """
                    INSERT INTO unresolved_incidents (
                        created_at, sanitized_error_log, highest_confidence_pct, status
                    ) VALUES (?, ?, ?, 'OPEN')
                    """,
                    (now_str, sanitized_query, confidence_pct)
                )
            conn.commit()

    def get_open_unresolved(self) -> List[Dict[str, Any]]:
        """Returns all unresolved incidents waiting for engineer remediation."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM unresolved_incidents WHERE status = 'OPEN' ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def promote_to_runbook(
        self,
        queue_id: int,
        incident_id: str,
        category: str,
        severity: str,
        error_code: str,
        symptom: str,
        root_cause: str,
        remediation: str,
        runbooks_dir: str = "data/raw_runbooks"
    ) -> str:
        """
        Formats a resolved incident into our standard Markdown runbook schema,
        appends it to '07_self_learned_runbooks.md', and marks the queue item RESOLVED.
        """
        os.makedirs(runbooks_dir, exist_ok=True)
        target_file = os.path.join(runbooks_dir, "07_self_learned_runbooks.md")

        new_block = (
            f"INCIDENT_ID: {incident_id.strip().upper()}\n"
            f"CATEGORY: {category.strip()}\n"
            f"SEVERITY: {severity.strip().upper()}\n"
            f"ERROR_CODE: {error_code.strip()}\n"
            f"SYMPTOM: {symptom.strip()}\n"
            f"ROOT CAUSE: {root_cause.strip()}\n"
            f"REMEDIATION:\n{remediation.strip()}"
        )

        # Append with '===' separator if file already has content
        if os.path.exists(target_file) and os.path.getsize(target_file) > 0:
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(f"\n===\n{new_block}")
        else:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(new_block)

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE unresolved_incidents
                SET status = 'PROMOTED', resolved_incident_id = ?
                WHERE id = ?
                """,
                (incident_id.strip().upper(), queue_id)
            )
            conn.commit()

        return target_file

    def get_telemetry_summary(self) -> Dict[str, Any]:
        """Aggregates KPI metrics for the analytics dashboard."""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM query_telemetry").fetchone()[0]
            passed = conn.execute("SELECT COUNT(*) FROM query_telemetry WHERE guardrail_status = 'PASSED'").fetchone()[0]
            blocked = conn.execute("SELECT COUNT(*) FROM query_telemetry WHERE guardrail_status = 'BLOCKED'").fetchone()[0]
            secrets = conn.execute("SELECT COALESCE(SUM(secrets_redacted), 0) FROM query_telemetry").fetchone()[0]
            avg_lat = conn.execute("SELECT COALESCE(AVG(latency_ms), 0.0) FROM query_telemetry").fetchone()[0]

            recent_rows = conn.execute(
                "SELECT * FROM query_telemetry ORDER BY id DESC LIMIT 20"
            ).fetchall()

        return {
            "total_queries": total,
            "passed_queries": passed,
            "blocked_queries": blocked,
            "total_secrets_scrubbed": secrets,
            "avg_latency_ms": round(avg_lat, 1),
            "recent_history": [dict(r) for r in recent_rows]
        }


# -------------------------------------------------------------------------
# SELF-TEST BLOCK: Test logging both a Passed and Blocked incident!
# -------------------------------------------------------------------------
if __name__ == "__main__":
    db = TelemetryDB()

    # 1. Simulate logging a PASSED query
    db.log_query_event(
        sanitized_query="psycopg2 OperationalError: too many clients connected to [REDACTED_IP]",
        secrets_redacted=1,
        top_chunk_id="PG-POOL-53300_chunk_0",
        vector_distance=0.2296,
        bm25_score=23.91,
        confidence_pct=100.0,
        guardrail_passed=True,
        latency_ms=142.5
    )

    # 2. Simulate logging a BLOCKED (Unseen) query
    db.log_query_event(
        sanitized_query="RabbitMQ AMQPConnectionError: Heartbeat timeout on channel 1",
        secrets_redacted=0,
        top_chunk_id="KAFKA-REBALANCE-404_chunk_0",
        vector_distance=0.7912,
        bm25_score=3.10,
        confidence_pct=4.2,
        guardrail_passed=False,
        latency_ms=118.0
    )

    summary = db.get_telemetry_summary()
    open_queue = db.get_open_unresolved()

    print("\n✅ SQLite Telemetry Summary:")
    print(f"   Total Queries: {summary['total_queries']} | Passed: {summary['passed_queries']} | Blocked: {summary['blocked_queries']}")
    print(f"   Secrets Scrubbed: {summary['total_secrets_scrubbed']} | Avg Latency: {summary['avg_latency_ms']} ms")
    print(f"\n📋 Open Unresolved Incidents Waiting for Self-Learning ({len(open_queue)}):")
    for item in open_queue:
        print(f"   [Queue ID #{item['id']}] Confidence: {item['highest_confidence_pct']}% | Log: {item['sanitized_error_log']}")