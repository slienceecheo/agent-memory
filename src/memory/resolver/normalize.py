"""主体与关系的归一化。

设计原则：**宁可不猜**。

- 归一不足 → 同一概念变成两条事实。表现为"记忆里有两份"，可见、可修。
- 归一过度 → 不同概念合并成一条。表现为"记忆里错了一份"，很难从结果发现。

所以未登记的表达一律保留原值，并用 `normalized=False` 标记，
让上层能统计"有多少输入没被覆盖"，而不是静默猜测。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# 关系别名表：值必须是规范名（左列）
_RELATION_ALIASES: dict[str, str] = {
    "包管理器": "package_manager",
    "包管理工具": "package_manager",
    "package manager": "package_manager",
    "包管理器工具": "package_manager",
    "测试命令": "test_command",
    "测试工具": "test_command",
    "test runner": "test_command",
    "测试框架": "test_command",
    "代码风格": "code_style",
    "格式化工具": "code_style",
    "formatter": "code_style",
    "linter": "code_style",
    "默认分支": "default_branch",
    "主分支": "default_branch",
    "default branch": "default_branch",
    "部署环境": "deploy_target",
    "部署目标": "deploy_target",
    "deploy target": "deploy_target",
    "值班人": "oncall_owner",
    "负责人": "oncall_owner",
    "oncall": "oncall_owner",
    "评审人": "reviewer",
    "reviewer": "reviewer",
    "开会时间": "meeting_time",
    "会议时间": "meeting_time",
    "meeting time": "meeting_time",
    "编码时间": "coding_time",
    "写代码时间": "coding_time",
    "coding time": "coding_time",
    "饮食禁忌": "dietary_restriction",
    "食物过敏": "dietary_restriction",
    "忌口": "dietary_restriction",
    "dietary restriction": "dietary_restriction",
    "allergy": "dietary_restriction",
}

_SUBJECT_ALIASES: dict[str, str] = {
    # 刻意不登记"这个仓库/本项目"这类指代词：
    # 它们在不同对话里指不同仓库，映射成同一个规范名会把所有项目合并成一个。
    # 这类指代应该由调用方在构造候选事实时解析为具体的 project id。
    "this repo": "project:default",
    "this project": "project:default",
}

_PLURAL_SUFFIXES = ("ies", "ses", "xes", "zes", "ches", "shes", "s")
_WHITESPACE = re.compile(r"\s+")


class InvalidKey(ValueError):
    """主体或关系归一化后为空。"""


@dataclass(frozen=True, slots=True)
class NormalizedKey:
    subject: str
    relation: str
    normalized: bool

    def as_tuple(self) -> tuple[str, str]:
        return (self.subject, self.relation)


def _basic(text: str) -> str:
    """全角转半角、去首尾空白、折叠内部空白、小写。"""
    folded = unicodedata.normalize("NFKC", text).strip().lower()
    return _WHITESPACE.sub(" ", folded)


def _singular(word: str) -> str:
    """极简单数化。只处理常见复数后缀，不做词形还原。

    词形还原引入的误判比它解决的多（例如 "news" → "new"）。
    """
    for suffix in _PLURAL_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            if suffix == "ies":
                return word[: -len(suffix)] + "y"
            return word[: -len(suffix)]
    return word


def _normalize_relation(text: str) -> tuple[str, bool]:
    basic = _basic(text)
    if not basic:
        raise InvalidKey("relation 归一化后为空，无法判定。")

    if basic in _RELATION_ALIASES:
        return _RELATION_ALIASES[basic], True

    # 先单数化再查别名：否则 "package_managers" 会漏掉
    singular = _singular(basic)
    if singular in _RELATION_ALIASES:
        return _RELATION_ALIASES[singular], True

    # 单数化后可能恰好是某个规范名的复数形式，例如 "package_managers"
    # → "package_manager"，它就是规范名本身
    for canonical in set(_RELATION_ALIASES.values()):
        if singular == canonical:
            return canonical, True

    # 未登记：保留原值（仅基础归一），并标记未归一
    return basic, False


def _normalize_subject(text: str) -> tuple[str, bool]:
    basic = _basic(text)
    if not basic:
        raise InvalidKey("subject 归一化后为空，无法判定。")

    if basic in _SUBJECT_ALIASES:
        return _SUBJECT_ALIASES[basic], True

    return basic, False


def normalize_key(subject: str, relation: str) -> NormalizedKey:
    """把主体与关系归一化为一对可比较的规范名。

    `normalized` 为 True 表示至少一侧走了别名表或复数归一。
    """
    normalized_subject, subject_hit = _normalize_subject(subject)
    normalized_relation, relation_hit = _normalize_relation(relation)
    return NormalizedKey(
        subject=normalized_subject,
        relation=normalized_relation,
        normalized=subject_hit or relation_hit,
    )
