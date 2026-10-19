"""Task 8 补充测试：钉住 `app/rag/search.run` 的 fake 路径。

fake 路径不依赖模型下载、不依赖 MySQL / Milvus，直接读 3 个政策 md →
切分 → FakeEmbedder → 内存 store → 检索 → 引用，端到端打印真实证据与引用。
"""
from app.rag.search import run


def test_run_fake_path_prints_citations(capsys):
    run("手机保修多久", real=False, top_k=5)
    out = capsys.readouterr().out
    assert "[1]" in out  # 至少打印一条编号引用
    assert "引用" in out
