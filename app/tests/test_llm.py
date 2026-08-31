"""Provider tests against a mocked Anthropic client.

These exist because the real call cannot be exercised in CI without a key, and the
first version of this code shipped a bug that only appeared against the live API:
it used assistant-message prefill to force JSON, which some models reject outright
with `400 invalid_request_error: This model does not support assistant message
prefill`. The request shape is now pinned by tests.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.backend import llm


class FakeMessages:
    def __init__(self, tool_result=None, text_result=None, tool_error=None, text_error=None):
        self.tool_result, self.text_result = tool_result, text_result
        self.tool_error, self.text_error = tool_error, text_error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "tools" in kwargs:
            if self.tool_error:
                raise self.tool_error
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self.tool_result)])
        if self.text_error:
            raise self.text_error
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text_result)])


def make_provider(messages: FakeMessages) -> llm.AnthropicProvider:
    p = llm.AnthropicProvider.__new__(llm.AnthropicProvider)   # skip API-key check
    p._client = SimpleNamespace(messages=messages)
    p.model = "test-model"
    return p


NOTES = {1: ("Note one", "ops needs a 25% increase on SSO")}
TOOL_PAYLOAD = {
    "bullets": [
        {"text": "Ops wants more SSO budget.", "note_id": 1,
         "quote": "ops needs a 25% increase on SSO", "invented": False},
        {"text": "Probably lands next quarter.", "note_id": None,
         "quote": None, "invented": True},
    ]
}


class TestRequestShape:
    def test_never_sends_an_assistant_prefill_message(self):
        """The exact bug that broke generation against the live API."""
        fake = FakeMessages(tool_result=TOOL_PAYLOAD)
        make_provider(fake).generate(NOTES, 2)
        for call in fake.calls:
            roles = [m["role"] for m in call["messages"]]
            assert "assistant" not in roles, f"assistant prefill reintroduced: {roles}"
            assert roles[-1] == "user", "conversation must end with a user message"

    def test_uses_forced_tool_choice(self):
        fake = FakeMessages(tool_result=TOOL_PAYLOAD)
        make_provider(fake).generate(NOTES, 2)
        call = fake.calls[0]
        assert call["tool_choice"] == {"type": "tool", "name": "submit_briefing"}
        assert call["tools"][0]["input_schema"]["required"] == ["bullets"]


class TestToolPath:
    def test_parses_a_tool_use_response(self):
        drafts = make_provider(FakeMessages(tool_result=TOOL_PAYLOAD)).generate(NOTES, 2)
        assert [d.text for d in drafts] == [
            "Ops wants more SSO budget.", "Probably lands next quarter."
        ]
        assert drafts[0].note_id == 1 and drafts[0].quote and not drafts[0].invented
        assert drafts[1].invented and drafts[1].note_id is None


class TestFallbackPath:
    def test_falls_back_to_text_when_tools_are_unsupported(self):
        fake = FakeMessages(
            tool_error=RuntimeError("400 tools not supported"),
            text_result='{"bullets": [{"text": "From text.", "note_id": 1, '
                        '"quote": "ops needs a 25% increase on SSO", "invented": false}]}',
        )
        drafts = make_provider(fake).generate(NOTES, 1)
        assert len(fake.calls) == 2, "should have retried without tools"
        assert "tools" not in fake.calls[1]
        assert drafts[0].text == "From text."

    def test_recovers_json_from_a_markdown_fence(self):
        fake = FakeMessages(
            tool_error=RuntimeError("nope"),
            text_result='Sure!\n```json\n{"bullets": [{"text": "Fenced.", "invented": true}]}\n```',
        )
        assert make_provider(fake).generate(NOTES, 1)[0].text == "Fenced."

    def test_both_paths_failing_gives_one_clear_error(self):
        fake = FakeMessages(
            tool_error=RuntimeError("tool boom"), text_error=RuntimeError("text boom")
        )
        with pytest.raises(RuntimeError) as exc:
            make_provider(fake).generate(NOTES, 1)
        assert "tool boom" in str(exc.value) and "text boom" in str(exc.value)


class TestCoercion:
    def test_drops_empty_bullets_and_normalises_types(self):
        drafts = llm._coerce({"bullets": [
            {"text": "  ", "invented": True},
            {"text": "Real.", "note_id": "3", "quote": "  ", "invented": False},
        ]})
        assert len(drafts) == 1
        assert drafts[0].note_id == 3            # string id coerced
        assert drafts[0].quote is None           # blank quote normalised away

    def test_missing_api_key_raises_a_useful_message(self, monkeypatch):
        monkeypatch.setattr(llm.settings, "anthropic_api_key", "")
        monkeypatch.setattr(llm.settings, "llm_provider", "anthropic")
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            llm.get_provider()
