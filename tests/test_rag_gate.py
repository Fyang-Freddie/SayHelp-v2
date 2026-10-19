from app.rag.retrieval import compute_evidence_confidence, passes_gate


def test_low_top1_fails_gate():
    c = compute_evidence_confidence(top1_score=0.1, evidence_count=1, margin=0.01)
    assert not passes_gate(c)


def test_strong_evidence_passes():
    c = compute_evidence_confidence(top1_score=0.9, evidence_count=3, margin=0.3)
    assert passes_gate(c)


def test_margin_and_count_matter():
    hi = compute_evidence_confidence(0.5, 3, 0.3)
    lo = compute_evidence_confidence(0.5, 1, 0.01)
    assert hi > lo
