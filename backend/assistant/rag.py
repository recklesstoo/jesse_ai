from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class DocChunk:
    path: str
    start_line: int
    end_line: int
    text: str


class DocIndex:
    """
    Lightweight local-doc RAG.

    Default implementation uses TF-IDF + cosine similarity when scikit-learn is available.
    Falls back to keyword scoring otherwise.
    """

    def __init__(
        self,
        repo_root: Path,
        include_paths: Sequence[str],
        *,
        max_file_bytes: int = 512_000,
        chunk_lines: int = 48,
        overlap_lines: int = 10,
    ) -> None:
        self.repo_root = repo_root
        self.include_paths = list(include_paths)
        self.max_file_bytes = int(max_file_bytes)
        self.chunk_lines = int(chunk_lines)
        self.overlap_lines = int(overlap_lines)

        self._chunks: List[DocChunk] = []
        self._vectorizer: Any = None
        self._matrix: Any = None
        self._built = False

    @property
    def built(self) -> bool:
        return bool(self._built)

    def _iter_files(self) -> Iterable[Path]:
        seen: set[str] = set()
        for rel in self.include_paths:
            p = (self.repo_root / rel).resolve()
            if not p.exists():
                continue

            if p.is_file():
                key = str(p).lower()
                if key in seen:
                    continue
                seen.add(key)
                yield p
                continue

            for file in p.rglob("*"):
                if not file.is_file():
                    continue
                if file.name.startswith("."):
                    continue
                if "__pycache__" in file.parts or "node_modules" in file.parts or ".venv" in file.parts:
                    continue
                key = str(file).lower()
                if key in seen:
                    continue
                seen.add(key)
                yield file

    def _read_text(self, p: Path) -> Optional[str]:
        try:
            size = p.stat().st_size
            if size <= 0 or size > self.max_file_bytes:
                return None
            raw = p.read_bytes()
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return None

    def _chunk_lines(self, rel_path: str, text: str) -> List[DocChunk]:
        lines = text.splitlines()
        if not lines:
            return []
        chunks: List[DocChunk] = []
        step = max(1, self.chunk_lines - self.overlap_lines)
        for start in range(0, len(lines), step):
            end = min(len(lines), start + self.chunk_lines)
            block = "\n".join(lines[start:end]).strip()
            if not block:
                continue
            chunks.append(DocChunk(path=rel_path, start_line=start + 1, end_line=end, text=block))
            if end >= len(lines):
                break
        return chunks

    def build(self) -> Dict[str, Any]:
        self._chunks = []
        for p in self._iter_files():
            rel = os.path.relpath(p, self.repo_root).replace("\\", "/")
            if not self._should_index(rel):
                continue
            text = self._read_text(p)
            if not text:
                continue
            self._chunks.extend(self._chunk_lines(rel, text))

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(
                lowercase=True,
                max_features=50_000,
                ngram_range=(1, 2),
                stop_words="english",
            )
            self._matrix = self._vectorizer.fit_transform([c.text for c in self._chunks]) if self._chunks else None
            mode = "tfidf"
        except Exception:
            self._vectorizer = None
            self._matrix = None
            mode = "keyword"

        self._built = True
        return {"ok": True, "chunks": len(self._chunks), "mode": mode}

    def _should_index(self, rel_path: str) -> bool:
        rel = rel_path.lower()
        if rel.endswith((".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".db", ".exe", ".dll")):
            return False
        # Default: docs + code + scripts (small allowlist).
        if rel.endswith((".md", ".py", ".jsx", ".js", ".ts", ".tsx", ".ps1", ".json")):
            return True
        return False

    def search(self, query: str, *, k: int = 5) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        if not self._built:
            self.build()
        if not self._chunks:
            return []

        if self._vectorizer is not None and self._matrix is not None:
            try:
                from sklearn.metrics.pairwise import cosine_similarity

                qv = self._vectorizer.transform([q])
                sims = cosine_similarity(qv, self._matrix).flatten()
                top_idx = sims.argsort()[::-1][: max(1, int(k))]
                out: List[Dict[str, Any]] = []
                for i in top_idx:
                    score = float(sims[i])
                    if score <= 0:
                        continue
                    c = self._chunks[int(i)]
                    out.append(
                        {
                            "type": "doc",
                            "path": c.path,
                            "start_line": c.start_line,
                            "end_line": c.end_line,
                            "snippet": c.text[:1800],
                            "score": round(score, 6),
                        }
                    )
                return out
            except Exception:
                # fall through
                pass

        # Keyword fallback.
        tokens = _tokenize(q)
        if not tokens:
            return []
        scored: List[Tuple[float, int]] = []
        for idx, chunk in enumerate(self._chunks):
            score = _keyword_score(tokens, chunk.text)
            if score > 0:
                scored.append((score, idx))
        scored.sort(reverse=True, key=lambda t: t[0])
        out = []
        for score, idx in scored[: max(1, int(k))]:
            c = self._chunks[idx]
            out.append(
                {
                    "type": "doc",
                    "path": c.path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "snippet": c.text[:1800],
                    "score": round(float(score), 6),
                }
            )
        return out


_word_re = re.compile(r"[a-zA-Z0-9_./:-]+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _word_re.findall(text or "") if len(t) >= 2]


def _keyword_score(tokens: Sequence[str], haystack: str) -> float:
    h = (haystack or "").lower()
    score = 0.0
    for t in tokens:
        if t in h:
            score += 1.0
    # Prefer concentrated matches.
    return score / max(1.0, (len(haystack) / 800.0))

