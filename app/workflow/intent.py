"""意图识别（INTENT）节点：把改写后的问题分类到 8 个意图之一。

对低置信度 / 未知意图 / 模型异常诚实兜底为「其他」，绝不强塞类别；
兜底时 confidence 一律 0.0。reason 在此以日志记录（飞轮归集 P6）。
"""
from __future__ import annotations

import logging

from app.llm.client import INTENTS, IntentModel, IntentResult

logger = logging.getLogger(__name__)


def classify_intent(intent_model: IntentModel, text: str, *, threshold: float) -> IntentResult:
    try:
        result = intent_model.classify(text)
    except Exception as exc:  # 含 jev 超时、网络错误、输出结构异常等
        logger.warning("intent classification failed: %s (fallback 其他)", exc)
        return IntentResult(intent="其他", confidence=0.0)

    if result.intent not in INTENTS:
        logger.warning(
            "intent %r not in INTENTS (fallback 其他)", result.intent
        )
        return IntentResult(intent="其他", confidence=0.0)

    if result.confidence < threshold:
        logger.warning(
            "intent %r confidence %.3f < threshold %.3f (fallback 其他)",
            result.intent,
            result.confidence,
            threshold,
        )
        return IntentResult(intent="其他", confidence=0.0)

    return result
