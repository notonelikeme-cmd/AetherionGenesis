# core/vector_memory.py
import threading

import faiss
import numpy as np

class VectorMemory:
    """
    Semantic memory using FAISS for embedding storage.
    """
    def __init__(self, dim):
        self.dim = dim
        self.index = faiss.IndexFlatL2(dim)
        self.metadata = []
        # add() is called from a separate thread per embedded bus
        # message (see VectorMemoryAgent), and it mutates the FAISS
        # index and the metadata list as two separate operations —
        # without a lock, concurrent adds can interleave and leave
        # metadata[i] pointing at the wrong index entry. search() takes
        # the same lock so it can't read mid-update either.
        self._lock = threading.Lock()

    def add(self, vector, meta):
        """
        Add a vector with associated metadata.
        """
        with self._lock:
            self.index.add(np.array([vector]).astype('float32'))
            self.metadata.append(meta)

    def search(self, query_vector, k=5):
        """
        Return top-k metadata for nearest neighbors to query_vector.
        """
        with self._lock:
            # FAISS pads results with sentinel index -1 when k exceeds the
            # number of stored vectors — self.metadata[-1] would then
            # return the *last* entry (wrong) or raise IndexError (empty
            # index). Bound k first so every returned index is real.
            if k <= 0 or self.index.ntotal == 0:
                return []
            k = min(k, self.index.ntotal)

            D, I = self.index.search(np.array([query_vector]).astype('float32'), k)
            results = []
            for distances, indices in zip(D, I):
                for dist, idx in zip(distances, indices):
                    if idx < 0:
                        continue
                    results.append((self.metadata[idx], dist))
            return results
