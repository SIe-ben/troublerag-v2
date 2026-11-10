# ⚡ TroubleRAG v2.0: Enterprise SRE Incident Resolution Engine

TroubleRAG v2.0 is an enterprise-grade, modular AI-powered Site Reliability Engineering (SRE) incident resolution assistant. It ingests enterprise runbooks, sanitizes private operational logs, executes a 3-stage hybrid search, enforces Cross-Encoder hallucination guardrails, and maintains an autonomous self-learning feedback loop.

---

## 🏗️ 6-Module Architecture

1. **PII & IP Sanitizer (`core/sanitizer.py`):** Automatically masks sensitive IP addresses, API tokens, and credentials using RegEx before vector processing.
2. **Context-Preserving Ingester (`core/ingestion.py`):** Parses markdown runbooks, extracts metadata headers (`INCIDENT_ID`, `CATEGORY`, `SEVERITY`, `ERROR_CODE`), and chunks text with context headers.
3. **Hybrid Retriever (`core/retriever.py`):** 
   - **Stage 1:** Parallel Dense Vector Search (ChromaDB + `all-MiniLM-L6-v2`) and Sparse Keyword Search (BM25).
   - **Stage 2:** Reciprocal Rank Fusion (RRF) for score normalization.
   - **Stage 3:** Deep Cross-Encoder Re-Ranking (`ms-marco-MiniLM-L-6-v2`) acting as a strict hallucination guardrail.
4. **Telemetry & Self-Learning Database (`core/database.py`):** SQLite persistence layer tracking query latencies, PII masking counts, and an unresolved incident queue for human-in-the-loop promotion.
5. **Context-Grounded Generator (`core/generator.py`):** Synthesizes precise engineering diagnostics using Groq Llama-3.3-70B or a deterministic offline markdown fallback engine.
6. **Automated Benchmark Suite (`evaluation/benchmark.py`):** Evaluates performance across in-domain error logs and out-of-domain adversarial prompts.

---

## 📊 Evaluation Metrics

* **Hit Rate @ 1:** 100.0%
* **Hit Rate @ 3:** 100.0%
* **Mean Reciprocal Rank (MRR):** 1.0000
* **Out-of-Domain Guardrail Rejection:** 100.0%

---

## 🚀 Getting Started & Usage Guide

### Prerequisites
* Python 3.10 or higher installed on your system.

### 1. Clone the Repository
```bash
git clone https://github.com/SIe-ben/troublerag-v2.git
cd troublerag-v2
```

### 2. Create and Activate a Virtual Environment
```bash
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Streamlit Dashboard
```bash
streamlit run app.py
```