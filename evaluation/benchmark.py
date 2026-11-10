import time
from typing import List, Dict, Any
from core.retriever import HybridRetriever


# Ground-Truth Evaluation Dataset: (Test Error Query, Expected Incident ID or 'BLOCK')
BENCHMARK_SUITE = [
    ("Container killed with ExitCode 137 SIGKILL cgroup memory limit exceeded", "K8S-OOM-137"),
    ("Pod stuck in ImagePullBackOff rpc error unauthorized authentication required", "K8S-IMAGEPULL-401"),
    ("Multi-Attach error for volume pvc already exclusively attached to one node", "K8S-PV-MOUNT-204"),
    ("psycopg2.OperationalError FATAL SQLSTATE 53300 remaining connection slots reserved", "PG-POOL-53300"),
    ("TransactionRollbackError SQLSTATE 40P01 deadlock detected Process waits for ShareLock", "PG-DEADLOCK-40P01"),
    ("PANIC could not write to file pg_wal xlogtemp No space left on device", "PG-WAL-DISK-53100"),
    ("database is not accepting commands to avoid wraparound data loss autovacuum freeze", "PG-XID-WRAPAROUND-22000"),
    ("nginx 502 Bad Gateway connect() failed 111 Connection refused while connecting to upstream", "NGINX-UPSTREAM-502"),
    ("socket.gaierror Errno -3 Temporary failure in name resolution CoreDNS timeout", "DNS-CORE-SERVFAIL"),
    ("SSLCertVerificationError certificate verify failed x509 certificate has expired", "TLS-CERT-EXPIRED-526"),
    ("RuntimeError CUDA out of memory Tried to allocate 512 MiB on GPU", "CUDA-VRAM-001"),
    ("OSError Errno 24 Too many open files ulimit socket failed", "LINUX-EMFILE-024"),
    # Adversarial / Out-of-Domain Queries (Must be BLOCKED by Cross-Encoder Guardrail < 25%)
    ("How to bake a chocolate fudge cake in a convection oven", "BLOCK"),
    (" Epson L3150 printer paper jam and cyan ink cartridge empty", "BLOCK"),
    ("React CSS flexbox align items center button border radius", "BLOCK"),
]


def run_evaluation(retriever: HybridRetriever, top_k: int = 3, confidence_cutoff: float = 25.0) -> Dict[str, Any]:
    """
    Runs the benchmark suite against the HybridRetriever and computes:
      - Hit Rate @ 1 and Hit Rate @ K
      - Mean Reciprocal Rank (MRR)
      - Adversarial Guardrail Rejection Accuracy
    """
    in_domain_total = 0
    hits_at_1 = 0
    hits_at_k = 0
    reciprocal_ranks = []

    adversarial_total = 0
    adversarial_blocked = 0

    detailed_rows: List[Dict[str, Any]] = []
    start_time = time.perf_counter()

    for query, expected_id in BENCHMARK_SUITE:
        t0 = time.perf_counter()
        results = retriever.search(query, top_k=top_k)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        top_confidence = results[0]["confidence_pct"] if results else 0.0
        retrieved_incident_ids = [r["metadata"]["incident_id"] for r in results]

        if expected_id == "BLOCK":
            adversarial_total += 1
            correctly_blocked = top_confidence < confidence_cutoff
            if correctly_blocked:
                adversarial_blocked += 1

            detailed_rows.append({
                "Query": query[:58] + "...",
                "Expected": "🛑 BLOCK (OOD)",
                "Top Predicted": f"Blocked ({top_confidence}%)" if correctly_blocked else retrieved_incident_ids[0],
                "Rank": "N/A",
                "Confidence (%)": top_confidence,
                "Latency (ms)": latency_ms,
                "Result": "✅ PASS" if correctly_blocked else "❌ FAIL"
            })
        else:
            in_domain_total += 1
            rank_found = None
            for idx, inc_id in enumerate(retrieved_incident_ids):
                if inc_id == expected_id and results[idx]["confidence_pct"] >= confidence_cutoff:
                    rank_found = idx + 1
                    break

            if rank_found == 1:
                hits_at_1 += 1
            if rank_found is not None:
                hits_at_k += 1
                reciprocal_ranks.append(1.0 / rank_found)
            else:
                reciprocal_ranks.append(0.0)

            detailed_rows.append({
                "Query": query[:58] + "...",
                "Expected": expected_id,
                "Top Predicted": retrieved_incident_ids[0] if retrieved_incident_ids else "None",
                "Rank": f"#{rank_found}" if rank_found else "Missed",
                "Confidence (%)": top_confidence,
                "Latency (ms)": latency_ms,
                "Result": "✅ PASS" if rank_found is not None else "❌ FAIL"
            })

    total_time_s = round(time.perf_counter() - start_time, 2)
    hit_rate_1 = round((hits_at_1 / in_domain_total) * 100, 1) if in_domain_total else 0.0
    hit_rate_k = round((hits_at_k / in_domain_total) * 100, 1) if in_domain_total else 0.0
    mrr_score = round(sum(reciprocal_ranks) / in_domain_total, 4) if in_domain_total else 0.0
    guardrail_acc = round((adversarial_blocked / adversarial_total) * 100, 1) if adversarial_total else 0.0

    return {
        "hit_rate_at_1": hit_rate_1,
        "hit_rate_at_k": hit_rate_k,
        "mrr": mrr_score,
        "guardrail_accuracy": guardrail_acc,
        "total_queries": len(BENCHMARK_SUITE),
        "total_time_s": total_time_s,
        "details": detailed_rows
    }


if __name__ == "__main__":
    print("⏳ Running TroubleRAG Automated Benchmark Suite (15 Test Cases)...")
    ret = HybridRetriever()
    metrics = run_evaluation(ret, top_k=3, confidence_cutoff=25.0)

    print("\n============================================================")
    print("📊 TROUBLERAG EVALUATION REPORT")
    print("============================================================")
    print(f"• Hit Rate @ 1          : {metrics['hit_rate_at_1']}%")
    print(f"• Hit Rate @ 3          : {metrics['hit_rate_at_k']}%")
    print(f"• Mean Reciprocal Rank  : {metrics['mrr']} (Max = 1.0000)")
    print(f"• Guardrail OOD Block   : {metrics['guardrail_accuracy']}%")
    print(f"• Total Benchmark Time  : {metrics['total_time_s']}s")
    print("============================================================\n")
    for row in metrics["details"]:
        print(f"{row['Result']} | Expected: {row['Expected']:<22} | Got: {row['Top Predicted']:<22} | Conf: {row['Confidence (%)']:>5}% | {row['Latency (ms)']}ms")