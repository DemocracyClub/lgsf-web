"""Stand-ins shared by the tests."""

import hashlib

from embeddings.embedders import EmbedderBase, Embedding


class FakeEmbedder(EmbedderBase):
    """Vectors made from each text's hash, keeping every text it's sent."""

    name = "fake"
    model = "fake-model-1"
    dimensions = 4

    def __init__(self):
        self.texts = []

    def vector(self, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[: self.dimensions]]

    def embed_documents(self, texts):
        self.texts.extend(texts)
        return [
            Embedding(vector=self.vector(text), token_count=len(text.split()))
            for text in texts
        ]

    def embed_query(self, text):
        return self.vector(text)
