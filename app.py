import time
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sklearn.decomposition import PCA

from core.sanitizer import LogSanitizer
from core.retriever import HybridRetriever
from core.database import TelemetryDB
from core.generator import IncidentGenerator
from evaluation.benchmark import run_evaluation


# ---------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & PRODUCTION DESIGN SYSTEM CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="TroubleRAG v2.0 | Enterprise SRE Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* Global Theme & Typography */
    .stApp {
        background-color: #090d16;
        color: #f1f5f9;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Hero Header Banner */
    .hero-banner {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #311042 100%);
        border: 1px solid rgba(99, 102, 241, 0.4);
        padding: 28px 36px;
        border-radius: 18px;
        margin-bottom: 24px;
        box-shadow: 0 20px 40px -15px rgba(79, 70, 229, 0.3);
    }
    .hero-title {
        font-size: 2.3rem;
        font-weight: 800;
        background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 6px;
        letter-spacing: -0.5px;
    }
    .hero-sub {
        color: #94a3b8;
        font-size: 1rem;
        margin: 0;
        font-weight: 400;
    }

    /* Glassmorphism Metric Cards */
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 18px 16px;
        text-align: center;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        border-color: rgba(99, 102, 241, 0.5);
    }
    .metric-val {
        font-size: 1.8rem;
        font-weight: 800;
        color: #38bdf8;
        line-height: 1.2;
    }
    .metric-lbl {
        font-size: 0.75rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        margin-top: 6px;
        font-weight: 600;
    }

    /* Section Containers */
    .panel-box {
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(51, 65, 85, 0.6);
        border-radius: 14px;
        padding: 22px;
        margin-bottom: 20px;
    }
    
    /* Streamlit Tab Styling Overrides */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(15, 23, 42, 0.5);
        padding: 6px;
        border-radius: 12px;
        border: 1px solid rgba(51, 65, 85, 0.5);
    }
    .stTabs [data-baseweb="tab"] {
        height: 42px;
        border-radius: 8px;
        color: #94a3b8;
        font-weight: 600;
        font-size: 0.9rem;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
        color: #ffffff !important;
        box-shadow: 0 4px 12px rgba(79, 70, 229, 0.4);
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 2. CACHED ENGINE INITIALIZATION
# ---------------------------------------------------------------------------
@st.cache_resource
def load_production_engines():
    sanitizer = LogSanitizer()
    retriever = HybridRetriever()
    db = TelemetryDB()
    generator = IncidentGenerator()
    return sanitizer, retriever, db, generator

sanitizer, retriever, db, generator = load_production_engines()


# ---------------------------------------------------------------------------
# 3. PRODUCTION SIDEBAR CONTROLS
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚡ SRE Control Center")
    groq_api_key = st.text_input("🔑 Groq API Key:", type="password", help="Enter free key from console.groq.com for Llama-3.3 neural synthesis")
    
    st.divider()
    st.markdown("### 🎛️ Pipeline Hyperparameters")
    top_k = st.slider("Top-K Chunks to Retrieve:", min_value=1, max_value=5, value=3, help="Number of context chunks fed to the re-ranker")
    confidence_threshold = st.slider("Guardrail Cutoff (%):", min_value=10.0, max_value=80.0, value=25.0, step=5.0, help="Minimum Cross-Encoder confidence required to pass guardrail")
    category_filter = st.selectbox(
        "📁 Target Domain Filter:",
        ["All", "Kubernetes", "PostgreSQL", "Networking / Nginx", "PyTorch / GPU", "Redis / Cache", "Linux Kernel / OS"]
    )
    
    st.divider()
    st.markdown("### 📊 System Telemetry")
    summary = db.get_telemetry_summary()
    st.metric("Total Queries Evaluated", summary["total_queries"])
    st.metric("PII / Secrets Masked", summary["total_secrets_scrubbed"])
    st.metric("Mean Pipeline Latency", f"{summary['avg_latency_ms']} ms")
    
    st.markdown("<br><p style='text-align: center; color: #64748b; font-size: 0.8rem;'>TroubleRAG v2.0 • Production Build</p>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 4. MAIN DASHBOARD HEADER
# ---------------------------------------------------------------------------
st.markdown("""
<div class="hero-banner">
    <div class="hero-title">⚡ TroubleRAG v2.0 Engine</div>
    <p class="hero-sub">Autonomous SRE Root Cause Analysis • Dense Vector Retrieval • Cross-Encoder Hallucination Guardrails</p>
</div>
""", unsafe_allow_html=True)

# Top Telemetry Glassmorphism Cards
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f'<div class="metric-card"><div class="metric-val">{retriever.collection.count()}</div><div class="metric-lbl">Indexed Chunks</div></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-card"><div class="metric-val">{summary["passed_queries"]}</div><div class="metric-lbl">Verified Resolutions</div></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><div class="metric-val">{summary["blocked_queries"]}</div><div class="metric-lbl">Guardrail Blocks</div></div>', unsafe_allow_html=True)
with m4:
    unresolved_count = len(db.get_open_unresolved())
    st.markdown(f'<div class="metric-card"><div class="metric-val" style="color: {"#f59e0b" if unresolved_count > 0 else "#38bdf8"}">{unresolved_count}</div><div class="metric-lbl">Unresolved Queue</div></div>', unsafe_allow_html=True)

st.write("<br>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 5. ENTERPRISE TAB ARCHITECTURE
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 Diagnostic Workspace",
    "🧠 Vector Space Explorer",
    "🔄 Self-Learning Queue",
    "📈 Audit & Telemetry Logs",
    "🎓 Automated Benchmarks"
])

with tab1:
    col_in, col_out = st.columns([1, 1.25], gap="large")
    
    with col_in:
        st.markdown("### 📥 Submit Production Incident Log")
        preset = st.selectbox(
            "⚡ Test Production Scenarios:",
            [
                "Custom Stack Trace / Error Log",
                "psycopg2.OperationalError: FATAL: remaining connection slots are reserved for non-replication superuser connections",
                "Pod worker-node terminated with exit status 137 and OOMKilled",
                "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB on GPU device",
                "nginx 502 Bad Gateway connect() failed (111: Connection refused) while connecting to upstream",
                "Unseen Error: RabbitMQ AMQPConnectionError heartbeat timeout on channel 1"
            ]
        )
        
        default_log = "" if preset == "Custom Stack Trace / Error Log" else preset
        raw_error_input = st.text_area("Paste Raw Terminal Log or Stack Trace:", value=default_log, height=160, placeholder="Paste logs containing stack traces, IP addresses, or error signatures...")
        
        run_rag_btn = st.button("🚀 Execute Hybrid RAG Pipeline", type="primary", use_container_width=True)

    with col_out:
        st.markdown("### 🔬 Execution Telemetry & Synthesis")
        if run_rag_btn and raw_error_input.strip():
            t_start = time.perf_counter()

            with st.status("🔄 Running Multi-Stage SRE Pipeline...", expanded=True) as status:
                st.write("🛡️ **Step 1:** Executing Regex PII & Secret Sanitization...")
                clean_query, redaction_stats = sanitizer.sanitize(raw_error_input)
                secrets_count = sum(redaction_stats.values())
                time.sleep(0.2)

                st.write("🔎 **Step 2:** Running 3-Stage Hybrid Search (ChromaDB Dense + BM25 Sparse)...")
                selected_cat = None if category_filter == "All" else category_filter
                retrieved_chunks = retriever.search(clean_query, top_k=top_k, category_filter=selected_cat)
                time.sleep(0.2)

                st.write("🎯 **Step 3:** Executing Cross-Encoder Deep Re-Ranking & Guardrail Validation...")
                top_chunk = retrieved_chunks[0] if retrieved_chunks else None
                top_confidence = top_chunk["confidence_pct"] if top_chunk else 0.0
                best_vec_dist = top_chunk["vector_distance"] if top_chunk else 1.0
                best_bm25 = top_chunk["bm25_score"] if top_chunk else 0.0
                guardrail_passed = top_confidence >= confidence_threshold
                time.sleep(0.2)

                latency = (time.perf_counter() - t_start) * 1000

                # SQLite Audit Logging
                db.log_query_event(
                    sanitized_query=clean_query,
                    secrets_redacted=secrets_count,
                    top_chunk_id=top_chunk["chunk_id"] if top_chunk else "NONE",
                    vector_distance=best_vec_dist,
                    bm25_score=best_bm25,
                    confidence_pct=top_confidence,
                    guardrail_passed=guardrail_passed,
                    latency_ms=latency
                )

                if guardrail_passed:
                    status.update(label=f"✅ Pipeline Complete — Verified Fix Retrieved ({latency:.1f}ms)", state="complete", expanded=False)
                else:
                    status.update(label=f"🛑 Guardrail Blocked — Unseen Anomaly Logged ({latency:.1f}ms)", state="error", expanded=False)

            # Security Notification Banner
            if secrets_count > 0:
                st.info(f"🛡️ **Security Layer Active:** Automatically scrubbed and masked `{secrets_count}` private credential(s)/IP(s) before vector querying.")

            # Guardrail Evaluation Output
            if not guardrail_passed:
                st.error(f"🛑 **Hallucination Guardrail Triggered!** Cross-Encoder Confidence (`{top_confidence}%`) is below threshold (`{confidence_threshold}%`).")
                st.warning("Execution halted to prevent AI hallucination. This unknown error signature has been automatically logged to the **Self-Learning Queue** (Tab 3).")
            else:
                # LLM Generation
                gen_result = generator.generate(clean_query, retrieved_chunks, api_key=groq_api_key)
                
                st.markdown(f"""
                <div style="background: rgba(16, 185, 129, 0.08); border-left: 4px solid #10b981; padding: 16px; border-radius: 8px; margin-bottom: 16px;">
                    <div style="font-weight: 700; color: #34d399; margin-bottom: 4px;">✅ DIAGNOSTIC SYNTHESIS COMPLETE</div>
                    <div style="color: #cbd5e1; font-size: 0.85rem;">Engine Mode: <b>{gen_result['mode']}</b> | Pipeline Latency: <b>{latency:.1f} ms</b></div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown(gen_result["answer"])

            # Interactive Speedometer / Confidence Gauge Chart
            if retrieved_chunks:
                fig_gauge = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=top_confidence,
                    number={'suffix': "%", 'font': {'color': "#38bdf8", 'size': 28}},
                    title={'text': "Cross-Encoder Confidence Score", 'font': {'color': "#cbd5e1", 'size': 13}},
                    gauge={
                        'axis': {'range': [0, 100], 'tickcolor': "#94a3b8"},
                        'bar': {'color': "#10b981" if guardrail_passed else "#ef4444"},
                        'bgcolor': "#0f172a",
                        'steps': [
                            {'range': [0, confidence_threshold], 'color': "rgba(239, 68, 68, 0.2)"},
                            {'range': [confidence_threshold, 100], 'color': "rgba(16, 185, 129, 0.2)"}
                        ]
                    }
                ))
                fig_gauge.update_layout(height=190, margin=dict(l=20, r=20, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", font={'color': "#cbd5e1"})
                st.plotly_chart(fig_gauge, use_container_width=True)
        else:
            st.info("👈 Select or paste an error log on the left and click **Execute Hybrid RAG Pipeline**.")

with tab2:
    st.markdown("### 🗺️ Semantic Vector Space Map (PCA Projection)")
    st.caption("Dimensionality reduction (384-D to 2-D PCA) displaying how ChromaDB clusters 87 enterprise runbook chunks across technology domains.")

    all_data = retriever.collection.get(include=["embeddings", "documents", "metadatas"])
    if all_data and all_data.get("embeddings") is not None and len(all_data["embeddings"]) > 0:
        embeddings = all_data["embeddings"]
        documents = all_data["documents"]
        metadatas = all_data["metadatas"]

        pca = PCA(n_components=2)
        coords = pca.fit_transform(embeddings)

        df_pca = pd.DataFrame({
            "PC1": coords[:, 0],
            "PC2": coords[:, 1],
            "Category": [m.get("category", "General") for m in metadatas],
            "Incident ID": [m.get("incident_id", "N/A") for m in metadatas],
            "Snippet": [doc[:130] + "..." for doc in documents]
        })

        fig_pca = px.scatter(
            df_pca, x="PC1", y="PC2", color="Category", hover_data=["Incident ID", "Snippet"],
            title="Interactive Cluster Map of Enterprise Runbooks", height=520
        )
        fig_pca.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,41,59,0.4)", font=dict(color="#cbd5e1"))
        st.plotly_chart(fig_pca, use_container_width=True)
    else:
        st.warning("Vector database is currently empty.")

with tab3:
    st.markdown("### 🔄 Self-Learning Incident Promotion Queue")
    st.caption("When unknown production errors trigger the guardrail, they are queued here. SRE engineers can inspect logs, verify fixes, and promote them instantly into ChromaDB & BM25.")

    open_queue = db.get_open_unresolved()
    if not open_queue:
        st.success("🎉 Queue is clear! All recent error logs successfully matched verified enterprise runbooks.")
    else:
        for item in open_queue:
            with st.expander(f"📌 [Queue ID #{item['id']}] Confidence: {item['highest_confidence_pct']}% — {item['sanitized_error_log'][:75]}..."):
                st.code(item["sanitized_error_log"], language="text")
                
                with st.form(f"promote_form_{item['id']}"):
                    c_col1, c_col2, c_col3 = st.columns(3)
                    with c_col1:
                        new_inc_id = st.text_input("Incident ID", value="CUSTOM-INC-001")
                    with c_col2:
                        new_cat = st.selectbox("Category", ["Kubernetes", "PostgreSQL", "Networking / Nginx", "PyTorch / GPU", "Redis / Cache", "Linux Kernel / OS"], key=f"cat_{item['id']}")
                    with c_col3:
                        new_sev = st.selectbox("Severity", ["CRITICAL", "HIGH", "MEDIUM"], key=f"sev_{item['id']}")
                    
                    new_err = st.text_input("Error Code Signature", value="CustomError / Exception", key=f"err_{item['id']}")
                    new_sym = st.text_input("Symptom Description", value=item["sanitized_error_log"][:80], key=f"sym_{item['id']}")
                    new_cause = st.text_input("Root Cause Explanation", value="Identified via autonomous production log monitoring.", key=f"cause_{item['id']}")
                    new_rem = st.text_area("Step-by-Step Remediation Playbook", value="1. Inspect service logs\n2. Apply patch", key=f"rem_{item['id']}")
                    
                    submitted = st.form_submit_button("🚀 Promote & Index Live into ChromaDB & BM25")
                    if submitted:
                        db.promote_to_runbook(
                            queue_id=item["id"],
                            incident_id=new_inc_id,
                            category=new_cat,
                            severity=new_sev,
                            error_code=new_err,
                            symptom=new_sym,
                            root_cause=new_cause,
                            remediation=new_rem
                        )
                        retriever._sync_indexes()
                        st.success(f"🎉 Successfully promoted `{new_inc_id}`! Vector index and BM25 matrix re-indexed live.")
                        st.rerun()

with tab4:
    st.markdown("### 📈 SQLite Audit Trail & Telemetry Logs")
    st.caption("Complete relational audit log recording every diagnostic query, PII redaction count, latency, and guardrail decision.")
    
    telemetry_data = db.get_telemetry_summary()
    history_rows = telemetry_data["recent_history"]

    if history_rows:
        df_audit = pd.DataFrame(history_rows)
        st.dataframe(df_audit, use_container_width=True, height=400)
    else:
        st.info("No query audit records found yet. Execute a diagnostic query in Tab 1.")

with tab5:
    st.markdown("### 🎓 Automated RAG Benchmark Suite")
    st.caption("Evaluates retrieval accuracy across 15 production test cases including in-domain runbooks and adversarial out-of-domain queries.")

    if st.button("🚀 Run Automated Evaluation Suite Now", type="primary"):
        with st.spinner("Executing 15 benchmark test cases..."):
            metrics = run_evaluation(retriever, top_k=3, confidence_cutoff=confidence_threshold)

        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Hit Rate @ 1", f"{metrics['hit_rate_at_1']}%")
        b2.metric("Hit Rate @ 3", f"{metrics['hit_rate_at_k']}%")
        b3.metric("Mean Reciprocal Rank (MRR)", f"{metrics['mrr']}")
        b4.metric("Guardrail OOD Rejection", f"{metrics['guardrail_accuracy']}%")

        df_bench = pd.DataFrame(metrics["details"])
        st.dataframe(df_bench, use_container_width=True, height=420)