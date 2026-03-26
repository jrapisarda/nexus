import hashlib

import numpy as np
from numpy.typing import NDArray


class EmbeddingService:
    """Lazy-loading embedding service using sentence-transformers."""

    def __init__(
        self, model_name: str = "all-MiniLM-L6-v2", device: str | None = None
    ):
        self._model_name = model_name
        self._device = device
        self._model = None

    def _load_model(self):
        """Lazy load the model on first use."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                import torch

                if self._device is None:
                    self._device = "cuda" if torch.cuda.is_available() else "cpu"
                self._model = SentenceTransformer(
                    self._model_name, device=self._device
                )
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for embeddings. "
                    "Install with: python -m pip install nexus-core[embeddings]"
                )

    def encode(self, text: str) -> NDArray[np.float32]:
        """Encode a single text to a 384-dim embedding vector."""
        self._load_model()
        return self._model.encode(text, normalize_embeddings=True)

    def batch_encode(self, texts: list[str]) -> NDArray[np.float32]:
        """Encode multiple texts to embedding vectors. Shape: (n, 384)."""
        self._load_model()
        return self._model.encode(texts, normalize_embeddings=True, batch_size=32)

    @staticmethod
    def hash_encode(text: str, dim: int = 384) -> NDArray[np.float32]:
        """Create a deterministic lightweight embedding without optional ML deps."""
        vector = np.zeros(dim, dtype=np.float32)
        tokens = [token for token in text.lower().split() if token]

        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector

        return vector / norm

    @staticmethod
    def cosine_similarity(
        a: NDArray[np.float32], b: NDArray[np.float32]
    ) -> float:
        """Compute cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    @staticmethod
    def pairwise_cosine_distances(
        embeddings: NDArray[np.float32],
    ) -> NDArray[np.float32]:
        """Compute pairwise cosine distances. Returns (n, n) matrix."""
        # Normalize rows
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalized = embeddings / norms
        # Cosine similarity matrix
        sim_matrix = normalized @ normalized.T
        # Convert to distance
        return 1.0 - sim_matrix

    @staticmethod
    def mean_pairwise_distance(embeddings: NDArray[np.float32]) -> float:
        """Calculate mean pairwise cosine distance (diversity metric)."""
        if len(embeddings) < 2:
            return 0.0
        distances = EmbeddingService.pairwise_cosine_distances(embeddings)
        n = len(embeddings)
        # Upper triangle only (exclude diagonal)
        upper_triangle = distances[np.triu_indices(n, k=1)]
        return float(np.mean(upper_triangle))
