import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.search import hybrid_search


@dataclass(frozen=True)
class EvalCase:
    query: str
    expected_law: str
    expected_article: str | None = None


def load_eval_cases(path: str | Path) -> list[EvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in data]


def _norm(text: str | None) -> str:
    return "".join((text or "").split()).lower()


def evaluate_retrieval(cases: list[EvalCase], top_k: int = 8) -> dict:
    results = []
    law_hits = 0
    article_hits = 0
    article_cases = 0

    for case in cases:
        hits = hybrid_search(case.query, top_k=top_k)
        expected_law = _norm(case.expected_law)
        expected_article = _norm(case.expected_article)
        law_hit = any(expected_law in _norm(hit.law_title) for hit in hits)
        article_hit = None
        if case.expected_article:
            article_cases += 1
            article_hit = any(
                expected_law in _norm(hit.law_title)
                and expected_article == _norm(hit.article_label)
                for hit in hits
            )
            article_hits += int(article_hit)
        law_hits += int(law_hit)
        results.append(
            {
                "case": asdict(case),
                "law_hit": law_hit,
                "article_hit": article_hit,
                "top_hits": [
                    {
                        "law_title": hit.law_title,
                        "article_label": hit.article_label,
                        "hybrid_score": hit.hybrid_score,
                    }
                    for hit in hits[: min(5, len(hits))]
                ],
            }
        )

    total = len(cases)
    return {
        "cases": total,
        "top_k": top_k,
        "law_hit_rate": law_hits / total if total else 0.0,
        "article_hit_rate": article_hits / article_cases if article_cases else None,
        "results": results,
    }
