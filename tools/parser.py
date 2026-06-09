"""
数据解析与去重。

将不同平台导出的原始数据解析为统一格式，
通过内容指纹去重，避免重复入库。
"""

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"


def load_fingerprints() -> set[str]:
    """扫描语料库中已有的内容指纹"""
    fingerprints = set()
    for txt_file in CORPUS.rglob("*.txt"):
        with open(txt_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("# fingerprint:"):
                    fingerprints.add(line.split(":")[1].strip())
    return fingerprints


def parse_qq_export(filepath: str) -> list[dict]:
    """
    解析 QQ 空间导出的数据。
    TODO: 根据实际导出格式实现。
    """
    raise NotImplementedError


def parse_wechat_export(filepath: str) -> list[dict]:
    """
    解析微信朋友圈导出的数据。
    TODO: 根据实际导出格式实现。
    """
    raise NotImplementedError


def deduplicate(articles: list[dict]) -> list[dict]:
    """去除已存在于语料库中的内容"""
    existing = load_fingerprints()
    new_articles = []
    for article in articles:
        fp = hashlib.sha256(
            article.get("content", "").encode("utf-8")
        ).hexdigest()[:16]
        if fp not in existing:
            article["fingerprint"] = fp
            new_articles.append(article)
    return new_articles


if __name__ == "__main__":
    print("[parser] 解析器骨架已加载，具体格式逻辑待实现")
