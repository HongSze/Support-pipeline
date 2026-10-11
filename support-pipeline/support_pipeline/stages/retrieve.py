"""TICKETS_CLASSIFIED -> KB_RETRIEVAL_COMPLETE

BM25 keyword scoring over every article in kb_articles.json (pure Python,
deterministic). The index is built only from the loaded KB file; there are no
hardcoded intent -> article or category mappings.

Score in [0, 1):  score = bm25 / (bm25 + SCORE_SATURATION)

Runs after classification so the query includes normalised ticket metadata:
the English working text plus the words of the classified intent label.

Output: retrieval_results.json
"""
from __future__ import annotations

import math
import re
from collections import Counter

from ..config import (BM25_B, BM25_K1, CLASSIFIED_FILE, PREPROCESSED_FILE, RETRIEVAL_FILE, RETRIEVAL_TOP_K,
                      SCORE_SATURATION, TAG_WEIGHT, TITLE_WEIGHT)
from .common import by_id

STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from has have i if in is it its me my no not of "
    "on or our please so that the their them then there this to was we what when where which who why "
    "will with you your again already now also any issue other hi team someone tell know".split()
)


def _stem(tok: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(tok) > 4 and tok.endswith(suffix) and not tok.endswith("ss"):
            return tok[: -len(suffix)]
    return tok


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("_", " ").replace("-", " ")
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = BM25_K1, b: float = BM25_B):
        self.docs, self.k1, self.b = docs, k1, b
        self.n = len(docs)
        self.avgdl = (sum(map(len, docs)) / self.n) if self.n else 0.0
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in docs]
        self.vocab = set(df)

    def score(self, query: list[str], i: int) -> tuple[float, list[str]]:
        tf, dl = self.tf[i], len(self.docs[i])
        total, matched = 0.0, []
        for term in dict.fromkeys(query):
            if term in tf:
                f = tf[term]
                norm = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                total += self.idf[term] * f * (self.k1 + 1) / norm
                matched.append(term)
        return total, matched


def _normalise(bm25: float) -> float:
    return round(bm25 / (bm25 + SCORE_SATURATION), 4) if bm25 > 0 else 0.0


def _article_text(article: dict) -> str:
    tags = " ".join(article["tags"])
    return " ".join([article["title"]] * TITLE_WEIGHT + [article["body"]] + [tags] * TAG_WEIGHT)


def analyse(kb: list[dict], preprocessed: list[dict], classified: list[dict]) -> list[dict]:
    """Full retrieval detail per ticket (scores, matched/unmatched terms). Deterministic, so the
    finalise stage can recompute it for the retrieval-quality notes without an extra file."""
    index = BM25([_tokenize_article(a) for a in kb])
    cls = by_id(classified)
    out = []
    for pre in preprocessed:
        tid = pre["ticket_id"]
        intent = cls[tid]["intent"]
        query = tokenize(f"{pre['subject_for_processing']} {pre['message_for_processing']} {intent}")
        scored = []
        for i, art in enumerate(kb):
            raw, matched = index.score(query, i)
            scored.append({"article_id": art["article_id"], "title": art["title"], "category": art["category"],
                           "score": _normalise(raw), "matched_terms": matched})
        scored.sort(key=lambda x: (-x["score"], x["article_id"]))
        top = scored[:RETRIEVAL_TOP_K]
        unique_query = list(dict.fromkeys(query))
        top_matched = set(top[0]["matched_terms"]) if top else set()
        out.append({
            "ticket_id": tid,
            "intent": intent,
            "top": top,
            "terms_unknown_to_kb": [t for t in unique_query if t not in index.vocab],
            "terms_not_in_top_article": [t for t in unique_query if t in index.vocab and t not in top_matched],
            "query_terms": unique_query,
        })
    return out


def _tokenize_article(article: dict) -> list[str]:
    return tokenize(_article_text(article))


def run(ctx) -> None:
    details = analyse(ctx.kb, ctx.load(PREPROCESSED_FILE), ctx.load(CLASSIFIED_FILE))
    records = [{
        "ticket_id": d["ticket_id"],
        "retrieved_articles": [{"article_id": a["article_id"], "title": a["title"], "score": a["score"]}
                               for a in d["top"]],
    } for d in details]
    ctx.save(RETRIEVAL_FILE, records)
    ctx.log(f"[retrieve] top {RETRIEVAL_TOP_K} articles per ticket -> {RETRIEVAL_FILE}")
