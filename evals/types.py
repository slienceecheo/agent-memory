"""评测结果的数据模型。

用 pydantic 而不是裸 dataclass：结果要落盘、要被报告脚本读、要能被 CI 比对，
序列化的稳定性比"轻量"更重要。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SampleResult(BaseModel):
    sample_id: str
    question: str
    gold: str
    prediction: str = ""
    correct: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    error: str | None = None

    @property
    def reasoning_waste_ratio(self) -> float:
        if self.completion_tokens <= 0:
            return 0.0
        return self.reasoning_tokens / self.completion_tokens


class BaselineResult(BaseModel):
    baseline: str
    benchmark: str
    subset: str
    samples: list[SampleResult] = Field(default_factory=list)

    @property
    def answered(self) -> list[SampleResult]:
        """只统计真正产出答案的样本；失败样本不参与准确率分母。"""
        return [sample for sample in self.samples if sample.error is None]

    @property
    def accuracy(self) -> float:
        answered = self.answered
        if not answered:
            return 0.0
        return sum(1 for sample in answered if sample.correct) / len(answered)

    @property
    def outcomes(self) -> list[bool]:
        return [sample.correct for sample in self.answered]

    @property
    def error_count(self) -> int:
        return sum(1 for sample in self.samples if sample.error is not None)

    @property
    def reasoning_waste_ratio(self) -> float:
        total_completion = sum(sample.completion_tokens for sample in self.samples)
        if total_completion <= 0:
            return 0.0
        total_reasoning = sum(sample.reasoning_tokens for sample in self.samples)
        return total_reasoning / total_completion
