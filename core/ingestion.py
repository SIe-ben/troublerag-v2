import os
import re
from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter


class RunbookIngestor:
    """
    Reads structured runbook files (.md / .txt), extracts metadata headers,
    and splits long documents into context-preserving chunks for ChromaDB & BM25.
    """

    def __init__(self, chunk_size: int = 450, chunk_overlap: int = 60):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )

    def _extract_field(self, text: str, field_name: str, default: str = "General") -> str:
        pattern = rf"^{field_name}:\s*(.+)$"
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        return match.group(1).strip() if match else default

    def parse_incident_block(self, raw_block: str, source_file: str) -> List[Dict[str, Any]]:
        incident_id = self._extract_field(raw_block, "INCIDENT_ID", "UNKNOWN-ID")
        category = self._extract_field(raw_block, "CATEGORY", "General")
        severity = self._extract_field(raw_block, "SEVERITY", "MEDIUM")
        error_code = self._extract_field(raw_block, "ERROR_CODE", "N/A")

        raw_chunks = self.splitter.split_text(raw_block.strip())
        processed_chunks: List[Dict[str, Any]] = []

        for idx, chunk_text in enumerate(raw_chunks):
            if f"INCIDENT_ID: {incident_id}" not in chunk_text:
                enriched_text = (
                    f"[CONTEXT: {incident_id} | {category} | {error_code}]\n"
                    f"{chunk_text}"
                )
            else:
                enriched_text = chunk_text

            chunk_record = {
                "chunk_id": f"{incident_id}_chunk_{idx}",
                "text": enriched_text,
                "metadata": {
                    "incident_id": incident_id,
                    "category": category,
                    "severity": severity,
                    "error_code": error_code,
                    "chunk_index": idx,
                    "source_file": source_file
                }
            }
            processed_chunks.append(chunk_record)

        return processed_chunks

    def load_directory(self, directory_path: str = "data/raw_runbooks") -> List[Dict[str, Any]]:
        all_chunks: List[Dict[str, Any]] = []

        if not os.path.exists(directory_path):
            raise FileNotFoundError(f"Runbook directory not found: {directory_path}")

        for filename in sorted(os.listdir(directory_path)):
            if filename.endswith((".md", ".txt")):
                file_path = os.path.join(directory_path, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                blocks = [b.strip() for b in content.split("===") if b.strip()]
                for block in blocks:
                    chunks = self.parse_incident_block(block, source_file=filename)
                    all_chunks.extend(chunks)

        return all_chunks


if __name__ == "__main__":
    ingestor = RunbookIngestor(chunk_size=450, chunk_overlap=60)
    chunks = ingestor.load_directory("data/raw_runbooks")

    print(f"\n✅ Total Chunks Generated: {len(chunks)}\n")
    
    for c in chunks[:3]:
        print(f"--- CHUNK ID: {c['chunk_id']} ---")
        print(f"Metadata : {c['metadata']}")
        print(f"Text     :\n{c['text']}\n")