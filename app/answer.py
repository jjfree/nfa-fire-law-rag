"""Evidence-grounded answer generation for the local fire-law RAG.

Retrieval remains deliberately separate from generation.  The answer layer sends
only current hybrid-search hits to a local Ollama model and keeps citation labels
stable so the UI/API can render the authoritative source metadata itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class AnswerGenerationError(RuntimeError):
    """Raised when the configured local answer model cannot produce a safe answer."""


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    status: str
    citations: tuple[int, ...] = ()
    error: str | None = None


def build_evidence_context(hits: list[Any], max_chars_per_hit: int = 5000) -> str:
    """Build a numbered, provenance-preserving context block for the LLM."""
    sections: list[str] = []
    for index, hit in enumerate(hits, start=1):
        article = hit.article_label or "未標示條號"
        heading = hit.heading or "未標示標題"
        content = hit.content[:max_chars_per_hit]
        sections.append(
            "\n".join(
                [
                    f"[{index}] 法規名稱：{hit.law_title}",
                    f"條號：{article}",
                    f"標題：{heading}",
                    f"版本：{hit.version_no}",
                    f"來源 URL：{hit.source_url}",
                    f"條文內容：\n{content}",
                ]
            )
        )
    return "\n\n---\n\n".join(sections)


def build_answer_prompt(query: str, evidence: str) -> str:
    """Create a strict Chinese legal-QA prompt with source-number citations."""
    return f"""你是台灣消防法規檢索助理。請使用繁體中文回答使用者問題。

回答規則：
1. 只能依據 <evidence> 內的現行法規片段回答；不得依記憶補充、猜測或創造法規內容。
2. 請先直接回答問題，再用簡短條列整理必要內容。
3. 每一個重要法律主張句末都必須附上證據編號，例如 [1] 或 [1][2]。
4. 證據編號只能使用 evidence 中存在的編號；不要自行輸出 URL 或不存在的編號。
5. 如果證據不足以回答，請明確說「目前檢索到的法規資料不足以確認」，並說明需要查找的內容。
6. 不要把檢索分數當成法律依據，也不要提供未附引用的法律結論。

<question>
{query}
</question>

<evidence>
{evidence}
</evidence>
"""


_CITATION_RE = re.compile(r"\[(\d+)\]")


def validate_citations(answer: str, evidence_count: int) -> tuple[int, ...]:
    """Return citation ids only when the model cited existing evidence."""
    citations = tuple(dict.fromkeys(int(value) for value in _CITATION_RE.findall(answer)))
    if not citations:
        raise AnswerGenerationError("模型回答沒有包含任何證據引用")
    invalid = [value for value in citations if value < 1 or value > evidence_count]
    if invalid:
        raise AnswerGenerationError(f"模型回答包含不存在的證據引用：{invalid}")
    return citations


class OllamaAnswerer:
    """Small synchronous client for Ollama's local chat endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        think: bool,
        max_output_tokens: int,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.think = think
        self.max_output_tokens = max_output_tokens

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你必須遵守使用者訊息中的法規證據與引用規則。",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": self.think,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_output_tokens,
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AnswerGenerationError(f"無法連線或解析 Ollama 回應：{type(exc).__name__}") from exc

        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise AnswerGenerationError("Ollama 回應沒有可用的文字內容")
        return content.strip()


def generate_answer(query: str, hits: list[Any]) -> AnswerResult:
    """Generate a cited answer from retrieved hits, without silently falling back."""
    if not hits:
        return AnswerResult(
            answer="目前檢索不到足以回答此問題的現行法規條文。",
            status="no_evidence",
        )

    settings = get_settings()
    provider = settings.llm_provider.lower().strip()
    if provider != "ollama":
        return AnswerResult(
            answer="已找到法規證據，但目前未啟用本機 LLM 生成回答。請查看下方條文，或設定 LLM_PROVIDER=ollama。",
            status="llm_disabled",
        )

    evidence = build_evidence_context(hits)
    prompt = build_answer_prompt(query, evidence)
    try:
        answer = OllamaAnswerer(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            think=settings.llm_think,
            max_output_tokens=settings.llm_max_output_tokens,
        ).complete(prompt)
        citations = validate_citations(answer, len(hits))
    except AnswerGenerationError as exc:
        return AnswerResult(
            answer="已找到法規證據，但本機 LLM 未產生可驗證的引用答案；請查看下方原文。",
            status="llm_error",
            error=str(exc),
        )
    return AnswerResult(answer=answer, status="ok", citations=citations)


def answer_question(query: str, hits: list[Any]) -> dict[str, Any]:
    """Return a serializable generation result for API, MCP, and UI callers."""
    result = generate_answer(query, hits)
    return {
        "answer": result.answer,
        "answer_status": result.status,
        "answer_citations": list(result.citations),
        **({"answer_error": result.error} if result.error else {}),
    }
