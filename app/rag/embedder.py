from typing import Protocol


class Embedder(Protocol):
    dim: int

    def encode_dense(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    def __init__(self, dim: int = 8):
        self.dim = dim

    def encode_dense(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(t):
                vec[i % self.dim] += ord(ch)
            out.append(vec)
        return out
