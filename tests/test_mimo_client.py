import json

import httpx
import pytest

from summarize.llm_client import LlmClientError
from summarize.mimo_client import MimoClient


def test_mimo_client_builds_openai_compatible_payload() -> None:
    client = MimoClient(api_key="secret", client=httpx.Client())

    payload = client.build_payload(
        messages=[{"role": "user", "content": "hello"}],
        model="mimo-v2-flash",
        response_schema={"type": "object"},
        temperature=0.2,
    )

    assert payload["model"] == "mimo-v2-flash"
    assert payload["messages"][0]["content"] == "hello"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["response_schema"] == {"type": "object"}
    assert payload["temperature"] == 0.2


def test_mimo_client_returns_json_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["api-key"] == "secret"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "mimo-v2-flash"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"paper_id":"1","title":"t","venue":"v","year":2025,"analysis":{},"classification":{},"latex_fields":{}}'}}]},
            request=request,
        )

    client = MimoClient(api_key="secret", client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.generate_json(messages=[{"role": "user", "content": "hello"}], model="mimo-v2-flash")

    assert json.loads(result)["paper_id"] == "1"


def test_mimo_client_rejects_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}, request=request)

    client = MimoClient(api_key="secret", client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(LlmClientError):
        client.generate_json(messages=[{"role": "user", "content": "hello"}], model="mimo-v2-flash")
