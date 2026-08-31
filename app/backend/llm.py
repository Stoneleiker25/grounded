"""LLM providers.

The prompt does one unusual thing: it asks the model to *supply the evidence for
its own claims* -- a verbatim quote per bullet -- and tells it plainly that the
quote will be checked against the note. That makes "cited" a falsifiable claim
rather than a label, and gives the model an honest way out (``invented: true``)
instead of forcing it to fabricate an attribution.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from .config import settings


@dataclass(frozen=True)
class DraftBullet:
    text: str
    note_id: int | None
    quote: str | None
    invented: bool


SYSTEM_PROMPT = """\
You write executive briefings from raw meeting notes.

Every bullet you produce must be one of exactly two kinds:

1. GROUNDED — the claim is supported by a specific note. You must supply:
   - "note_id": the id of that note
   - "quote": a VERBATIM span copied from that note's body that supports the claim.
     Copy it character-for-character. Do not fix typos, expand abbreviations,
     change punctuation, or paraphrase. The quote is checked programmatically
     against the note text; a rewritten quote will fail and your bullet will be
     downgraded to invented.

2. INVENTED — connective tissue, inference, or anything you cannot point at a note
   for. Set "invented": true and leave note_id and quote null.

Being wrong about grounding is much worse than admitting invention. If you are not
certain a note supports a claim, mark it invented. There is no penalty for saying
so, and the human reader is shown both kinds.

Write in plain professional English. One fact per bullet. No preamble, no closing
summary, no markdown formatting inside bullet text.

Return ONLY a JSON object of this exact shape:
{"bullets": [{"text": "...", "note_id": 3, "quote": "...", "invented": false}]}
"""


def build_user_prompt(notes: dict[int, tuple[str, str]], n_bullets: int) -> str:
    blocks = []
    for note_id, (title, body) in sorted(notes.items()):
        blocks.append(f'<note id="{note_id}" title="{title}">\n{body}\n</note>')
    return (
        f"Here are {len(notes)} source notes.\n\n"
        + "\n\n".join(blocks)
        + f"\n\nWrite exactly {n_bullets} briefing bullets following the rules. "
        "Prefer grounded bullets. Mark anything you cannot support as invented."
    )


class LLMProvider(Protocol):
    name: str

    def generate(self, notes: dict[int, tuple[str, str]], n_bullets: int) -> list[DraftBullet]:
        ...


def _coerce(payload: dict) -> list[DraftBullet]:
    out: list[DraftBullet] = []
    for raw in payload.get("bullets", []):
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        invented = bool(raw.get("invented"))
        note_id = raw.get("note_id")
        try:
            note_id = int(note_id) if note_id is not None else None
        except (TypeError, ValueError):
            note_id = None
        quote = raw.get("quote")
        quote = quote.strip() if isinstance(quote, str) and quote.strip() else None
        out.append(DraftBullet(text=text, note_id=note_id, quote=quote, invented=invented))
    return out


def _extract_json(text: str) -> dict:
    """Models occasionally wrap JSON in prose or a fence. Recover rather than fail."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "GROUNDED_ANTHROPIC_API_KEY is not set. Copy .env.example to .env and "
                "add your key (get one at https://console.anthropic.com)."
            )
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def generate(self, notes: dict[int, tuple[str, str]], n_bullets: int) -> list[DraftBullet]:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": build_user_prompt(notes, n_bullets)},
                # Prefill forces the response to start as JSON.
                {"role": "assistant", "content": "{"},
            ],
        )
        body = "{" + "".join(b.text for b in resp.content if b.type == "text")
        return _coerce(_extract_json(body))


class EchoProvider:
    """Deterministic stand-in used by the test suite ONLY.

    It is not an "AI" implementation and is never used by the running app unless
    GROUNDED_LLM_PROVIDER=echo is set explicitly. It exists so the verification
    pipeline can be tested without network access, including the cases a real
    model produces rarely and unpredictably: a good citation, a mis-attributed
    one, a fabricated quote, and an honest refusal.
    """

    name = "echo"

    def generate(self, notes: dict[int, tuple[str, str]], n_bullets: int) -> list[DraftBullet]:
        ids = sorted(notes)
        drafts: list[DraftBullet] = []
        for i, note_id in enumerate(ids):
            _, body = notes[note_id]
            first = re.split(r"(?<=[.!?])\s+|\n", body.strip())[0][:160]
            if i % 4 == 3:
                drafts.append(DraftBullet(f"Follow-up needed on note {note_id}.", None, None, True))
            elif i % 4 == 2:
                drafts.append(DraftBullet(
                    f"Unsupported claim about note {note_id}.", note_id,
                    "this sentence appears in no note whatsoever", False))
            else:
                wrong = ids[(i + 1) % len(ids)] if len(ids) > 1 and i % 4 == 1 else note_id
                drafts.append(DraftBullet(first, wrong, first, False))
        while len(drafts) < n_bullets:
            drafts.append(DraftBullet(f"Additional context item {len(drafts)+1}.", None, None, True))
        return drafts[:n_bullets]


def get_provider() -> LLMProvider:
    if settings.llm_provider == "echo":
        return EchoProvider()
    if settings.llm_provider == "anthropic":
        return AnthropicProvider()
    raise RuntimeError(f"Unknown GROUNDED_LLM_PROVIDER: {settings.llm_provider!r}")
