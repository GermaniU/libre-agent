"""Rescue of text-embedded tool calls (Hermes/Qwen <tool_call> format).

Some local models (Bonsai, qwen-coder…) write the tool call as text instead of using
ollama's structured tool_calls field; clients._parse_text_tool_calls recovers them.
"""
import clients


def test_parses_single_tool_call():
    text = '<tool_call>{"name": "web_search", "arguments": {"query": "MCP"}}</tool_call>'
    calls = clients._parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "web_search"
    assert calls[0]["function"]["arguments"] == {"query": "MCP"}


def test_parses_multiple_and_multiline():
    text = (
        'primero esto\n<tool_call>\n{"name": "vault_search", "arguments": {"query": "x"}}\n</tool_call>\n'
        'y esto\n<tool_call>{"name": "web_fetch", "arguments": {"url": "http://a"}}</tool_call>'
    )
    calls = clients._parse_text_tool_calls(text)
    assert [c["function"]["name"] for c in calls] == ["vault_search", "web_fetch"]


def test_plain_json_is_not_a_tool_call():
    # a normal answer that happens to contain JSON must NOT be treated as a tool call
    text = 'Acá tenés un ejemplo: {"name": "Germani", "edad": 30}'
    assert clients._parse_text_tool_calls(text) == []


def test_ignores_malformed_block():
    text = '<tool_call>{esto no es json}</tool_call>'
    assert clients._parse_text_tool_calls(text) == []


def test_accepts_parameters_alias():
    text = '<tool_call>{"name": "run_cmd", "parameters": {"command": "ls"}}</tool_call>'
    calls = clients._parse_text_tool_calls(text)
    assert calls[0]["function"]["arguments"] == {"command": "ls"}


def test_closing_tag_only():
    # the real Bonsai case: no opening tag, JSON then </tool_call>
    text = '{"name": "web_search", "arguments": {"query": "Ternary Bonsai"}}\n</tool_call>'
    calls = clients._parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "web_search"


def test_braces_inside_string_value():
    # write_file with code containing braces must parse as ONE call
    text = '{"name": "write_file", "arguments": {"path": "x.py", "content": "def f(): return {1:2}"}}</tool_call>'
    calls = clients._parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["arguments"]["path"] == "x.py"
