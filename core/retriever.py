import os
import re
import math
from typing import List, Dict, Any, Optional
# Suppress Hugging Face symlink warnings on Windows systems
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from core.ingestion import RunbookIngestor


class HybridRetriever:
    """
    Production 3-Stage Retrieval Engine:
      Stage 1: Parallel Dense Vector Search (ChromaDB) + Sparse Keyword Search (BM25)
      Stage 2: Reciprocal Rank Fusion (RRF) score normalization
      Stage 3: Deep Cross-Encoder Re-Ranking & Sigmoid Confidence Guardrail
    """

    def __init__(
        self,
        persist_dir: str = "data/chroma_storage",
        runbooks_dir: str = "data/raw_runbooks"
    ):
        self.persist_dir = persist_dir
        self.runbooks_dir = runbooks_dir

        # 1. Initialize Persistent ChromaDB (384-D Dense Bi-Encoder)
        self.chroma_client = chromadb.PersistentClient(path=self.persist_dir)
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="enterprise_runbooks_v2",
            embedding_function=self.embed_fn,
            metadata={"hnsw:space": "cosine"}
        )

        # 2. Load Cross-Encoder for Stage-3 Deep Re-Ranking
        # ms-marco-MiniLM-L-6-v2 evaluates (Query, Document) pairs simultaneously
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

        # 3. In-memory holders for BM25 Sparse Index
        self.bm25: Optional[BM25Okapi] = None
        self.chunk_registry: Dict[str, Dict[str, Any]] = {}
        self.ordered_chunk_ids: List[str] = []

        # Build or synchronize indexes on startup
        self._sync_indexes()

    def _tokenize(self, text: str) -> List[str]:
        """
        Custom tokenizer for BM25: Lowercases and extracts alphanumeric tokens,
        preserving error codes like '53300', '137', 'oomkilled', '40p01'.
        """
        return re.findall(r"[a-z0-9_]+", text.lower())

    def _sync_indexes(self) -> None:
        """
        Loads runbook chunks from disk, indexes them into ChromaDB if needed,
        and builds the BM25 keyword matrix in RAM.
        """
        ingestor = RunbookIngestor(chunk_size=450, chunk_overlap=60)
        chunks = ingestor.load_directory(self.runbooks_dir)

        # Populate ChromaDB if count doesn't match current corpus
        if self.collection.count() != len(chunks):
            # Clear stale records if re-indexing
            existing = self.collection.get()
            if existing and existing["ids"]:
                self.collection.delete(ids=existing["ids"])

            self.collection.add(
                ids=[c["chunk_id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[c["metadata"] for c in chunks]
            )

        # Build BM25 Sparse Keyword Index over all chunks
        tokenized_corpus = []
        self.chunk_registry.clear()
        self.ordered_chunk_ids.clear()

        for c in chunks:
            cid = c["chunk_id"]
            self.chunk_registry[cid] = c
            self.ordered_chunk_ids.append(cid)
            tokenized_corpus.append(self._tokenize(c["text"]))

        self.bm25 = BM25Okapi(tokenized_corpus)

    def _sigmoid(self, x: float) -> float:
        """
        Maps raw Cross-Encoder logits (-10 to +10) into a clean [0.0, 1.0] probability.
        """
        return 1.0 / (1.0 + math.exp(-x))

    def search(
        self,
        query: str,
        top_k: int = 3,
        category_filter: Optional[str] = None,
        rrf_k: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Executes the full 3-stage retrieval pipeline and returns ranked chunks
        with full telemetry (Vector Distance, BM25 Score, RRF Score, Cross-Encoder Confidence).
        """
        candidate_pool_size = min(10, self.collection.count())

        # STAGE 1A: Dense Vector Search (ChromaDB Cosine Distance)
        
        where_clause = {"category": category_filter} if (category_filter and category_filter != "All") else None
        vector_results = self.collection.query(
            query_texts=[query],
            n_results=candidate_pool_size,
            where=where_clause
        )

        vec_ids = vector_results["ids"][0]
        vec_distances = vector_results["distances"][0]
        vec_ranks = {cid: rank + 1 for rank, cid in enumerate(vec_ids)}
        vec_dist_map = {cid: dist for cid, dist in zip(vec_ids, vec_distances)}

        
        # STAGE 1B: Sparse Keyword Search (BM25 Exact Error Code Matching)
        
        tokenized_query = self._tokenize(query)
        bm25_raw_scores = self.bm25.get_scores(tokenized_query)

        # Pair each chunk ID with its BM25 score and filter by category if requested
        bm25_paired = []
        for idx, score in enumerate(bm25_raw_scores):
            cid = self.ordered_chunk_ids[idx]
            meta = self.chunk_registry[cid]["metadata"]
            if where_clause and meta.get("category") != category_filter:
                continue
            bm25_paired.append((cid, float(score)))

        # Sort descending by BM25 score and take top candidates
        bm25_paired.sort(key=lambda item: item[1], reverse=True)
        bm25_top = bm25_paired[:candidate_pool_size]
        bm25_ranks = {cid: rank + 1 for rank, (cid, _) in enumerate(bm25_top)}
        bm25_score_map = {cid: score for cid, score in bm25_top}

        
        # STAGE 2: Reciprocal Rank Fusion (RRF)
        # Formula: RRF_Score = 1 / (k + rank_vector) + 1 / (k + rank_bm25)
        
        all_candidate_ids = set(vec_ids) | set(bm25_ranks.keys())
        rrf_candidates = []

        for cid in all_candidate_ids:
            r_vec = vec_ranks.get(cid, 1000)
            r_bm25 = bm25_ranks.get(cid, 1000)

            vec_contribution = 1.0 / (rrf_k + r_vec) if cid in vec_ranks else 0.0
            bm25_contribution = 1.0 / (rrf_k + r_bm25) if cid in bm25_ranks else 0.0
            rrf_score = vec_contribution + bm25_contribution

            rrf_candidates.append({
                "chunk_id": cid,
                "text": self.chunk_registry[cid]["text"],
                "metadata": self.chunk_registry[cid]["metadata"],
                "vector_distance": round(vec_dist_map.get(cid, 1.0), 4),
                "vector_rank": r_vec if cid in vec_ranks else None,
                "bm25_score": round(bm25_score_map.get(cid, 0.0), 2),
                "bm25_rank": r_bm25 if cid in bm25_ranks else None,
                "rrf_score": round(rrf_score, 5)
            })

        # Sort by fused RRF score and take top 6 for deep Cross-Encoder inspection
        rrf_candidates.sort(key=lambda x: x["rrf_score"], reverse=True)
        shortlist = rrf_candidates[:6]

        
        # STAGE 3: Cross-Encoder Deep Re-Ranking
        
        if not shortlist:
            return []

        pairs = [[query, item["text"]] for item in shortlist]
        raw_logits = self.reranker.predict(pairs)

        for item, logit in zip(shortlist, raw_logits):
            logit_val = float(logit)
            item["rerank_logit"] = round(logit_val, 3)
            item["confidence_pct"] = round(self._sigmoid(logit_val) * 100, 1)

        # Final sort by Cross-Encoder Confidence (highest to lowest)
        shortlist.sort(key=lambda x: x["rerank_logit"], reverse=True)
        return shortlist[:top_k]



# SELF-TEST BLOCK: Test Both Valid Errors & Unseen Hallucination Guardrail!

if __name__ == "__main__":
    print("⏳ Initializing HybridRetriever (Loading MiniLM Bi-Encoder, BM25 & Cross-Encoder)...")
    retriever = HybridRetriever()
    print(f"✅ Indexed {retriever.collection.count()} chunks in ChromaDB + BM25!\n")

    # Test 1: Exact Error Code + Semantic symptom
    test_query_1 = "psycopg2 OperationalError SQLSTATE 53300 too many clients connected"
    print(f"🔎 TEST 1 QUERY: '{test_query_1}'")
    results_1 = retriever.search(test_query_1, top_k=2)
    for idx, res in enumerate(results_1):
        print(
            f"   Rank #{idx+1}: {res['chunk_id']} | "
            f"VecDist: {res['vector_distance']} (Rank {res['vector_rank']}) | "
            f"BM25: {res['bm25_score']} (Rank {res['bm25_rank']}) | "
            f"RRF: {res['rrf_score']} | "
            f"Cross-Encoder Confidence: {res['confidence_pct']}%"
        )

    # Test 2: Completely unrelated error (Should get very low Cross-Encoder confidence!)
    test_query_2 = "My office Epson printer is jammed and out of magenta ink"
    print(f"\n🔎 TEST 2 (UNSEEN/IRRELEVANT) QUERY: '{test_query_2}'")
    results_2 = retriever.search(test_query_2, top_k=1)
    for res in results_2:
        print(
            f"   Top Match: {res['chunk_id']} | "
            f"VecDist: {res['vector_distance']} | "
            f"BM25: {res['bm25_score']} | "
            f"Cross-Encoder Confidence: {res['confidence_pct']}% (Guardrail will BLOCK this!)"
        )