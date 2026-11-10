import os
from typing import List, Dict, Any, Optional
from groq import Groq


class IncidentGenerator:
    """
    Context-Grounded Synthesis Engine (The 'A' and 'G' in RAG):
      1. Formats retrieved hybrid chunks with strict source citation headers.
      2. Calls Groq Llama-3.3-70B with temperature=0.1 for zero-hallucination synthesis.
      3. Provides an automatic deterministic offline fallback if no API key is present.
    """

    def __init__(self, model_name: str = "llama-3.3-70b-versatile"):
        self.model_name = model_name
        self.system_prompt = (
            "You are TroubleRAG, a Senior Principal Site Reliability Engineering AI created by Joy. "
            "You must diagnose the user's sanitized error log using ONLY the verified runbook chunks provided below.\n\n"
            "STRICT RULES:\n"
            "1. NEVER invent terminal commands, flags, or configuration parameters not present in the context.\n"
            "2. Always cite the exact [Chunk ID] and [Incident ID] in your explanation.\n"
            "3. Structure your response using these exact Markdown headings:\n"
            "   ### 🎯 Executive Root Cause Analysis\n"
            "   ### 🔬 Diagnostic Verification Steps\n"
            "   ### 🛠️ Verified Remediation Commands\n"
        )

    def build_augmented_context(self, retrieved_chunks: List[Dict[str, Any]]) -> str:
        """
        Formats the top-k retrieved chunks into a numbered, citation-tagged block
        so the LLM (and the user) can see the exact provenance of every fact.
        """
        blocks = []
        for idx, item in enumerate(retrieved_chunks):
            meta = item.get("metadata", {})
            header = (
                f"--- VERIFIED SOURCE #{idx + 1} ---\n"
                f"CHUNK_ID: {item['chunk_id']}\n"
                f"INCIDENT_ID: {meta.get('incident_id', 'N/A')} | "
                f"CATEGORY: {meta.get('category', 'General')} | "
                f"SEVERITY: {meta.get('severity', 'HIGH')}\n"
                f"CROSS_ENCODER_CONFIDENCE: {item.get('confidence_pct', 0.0)}%\n"
                f"CONTENT:\n{item['text']}"
            )
            blocks.append(header)
        return "\n\n".join(blocks)

    def _offline_deterministic_synthesis(
        self,
        sanitized_query: str,
        retrieved_chunks: List[Dict[str, Any]]
    ) -> str:
        """
        Offline Extractive Synthesis: Guarantees a structured engineering report
        even when running without an internet connection or Groq API key.
        """
        top = retrieved_chunks[0]
        meta = top.get("metadata", {})
        combined_text = "\n\n".join([c["text"] for c in retrieved_chunks])

        return (
            f"### 🎯 Matched Incident: `{meta.get('incident_id', 'UNKNOWN')}` ({meta.get('category', 'General')})\n"
            f"* **Severity Level:** `{meta.get('severity', 'HIGH')}` | **Cross-Encoder Confidence:** `{top.get('confidence_pct')}%`\n"
            f"* **Primary Source Chunk:** `{top['chunk_id']}` (File: `{meta.get('source_file')}`)\n"
            f"* **Synthesis Mode:** `Deterministic Offline Engine` *(Enter a free Groq API Key in the sidebar to enable live Llama-3.3-70B neural synthesis)*\n\n"
            f"---\n"
            f"### 📋 Verified Runbook Remediation Playbook\n"
            f"```markdown\n{combined_text}\n```"
        )

    def generate(
        self,
        sanitized_query: str,
        retrieved_chunks: List[Dict[str, Any]],
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes prompt augmentation and returns a dictionary containing:
          - answer: The formatted Markdown diagnosis
          - mode: 'Llama-3.3-70B (Cloud API)' or 'Offline Extractive Engine'
          - augmented_prompt: The exact prompt payload for UI inspection
        """
        if not retrieved_chunks:
            return {
                "answer": "No verified context chunks available for synthesis.",
                "mode": "Blocked",
                "augmented_prompt": ""
            }

        formatted_context = self.build_augmented_context(retrieved_chunks)
        user_prompt = (
            f"SANITIZED USER ERROR LOG:\n{sanitized_query}\n\n"
            f"VERIFIED RUNBOOK CONTEXT:\n{formatted_context}"
        )

        # Check for API key in argument or environment variable
        active_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()

        if not active_key:
            return {
                "answer": self._offline_deterministic_synthesis(sanitized_query, retrieved_chunks),
                "mode": "Offline Extractive Engine",
                "augmented_prompt": user_prompt
            }

        try:
            client = Groq(api_key=active_key)
            completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=700
            )
            return {
                "answer": completion.choices[0].message.content,
                "mode": f"Groq ({self.model_name})",
                "augmented_prompt": user_prompt
            }
        except Exception as e:
            fallback = self._offline_deterministic_synthesis(sanitized_query, retrieved_chunks)
            return {
                "answer": f"⚠️ **Cloud API Notice:** `{str(e)}` — Automatically switched to Offline Extractive Engine:\n\n{fallback}",
                "mode": "Offline Fallback",
                "augmented_prompt": user_prompt
            }


# -------------------------------------------------------------------------
# SELF-TEST BLOCK: Test Prompt Augmentation & Synthesis
# -------------------------------------------------------------------------
if __name__ == "__main__":
    from core.retriever import HybridRetriever

    retriever = HybridRetriever()
    generator = IncidentGenerator()

    sample_query = "Pod worker-node crashed with ExitCode 137 OOMKilled"
    chunks = retriever.search(sample_query, top_k=2)

    result = generator.generate(sample_query, chunks, api_key=None)
    print(f"\n✅ Generation Mode: {result['mode']}")
    print("\n--- GENERATED OUTPUT PREVIEW ---")
    print(result["answer"][:600] + "\n...[truncated]...")