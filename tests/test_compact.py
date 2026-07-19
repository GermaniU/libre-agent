"""agent.compact_messages — pure helper that collapses old messages into a summary."""
import agent


def test_compact_keeps_last_n_and_prepends_summary():
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg{i}"}
                for i in range(6)]
    result = agent.compact_messages(messages, "resumen de prueba", keep=2)
    assert len(result) == 3
    assert result[0]["role"] == "assistant"
    assert "resumen de prueba" in result[0]["content"]
    assert result[1:] == messages[-2:]


def test_compact_noop_when_not_enough_messages():
    messages = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hey"}]
    result = agent.compact_messages(messages, "resumen", keep=4)
    assert result == messages


def test_compact_noop_when_exactly_at_keep_limit():
    messages = [{"role": "user", "content": f"m{i}"} for i in range(4)]
    result = agent.compact_messages(messages, "resumen", keep=4)
    assert result == messages


def test_summary_appears_in_first_message_content():
    messages = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    result = agent.compact_messages(messages, "decisiones clave y datos", keep=3)
    assert "decisiones clave y datos" in result[0]["content"]
    assert result[0]["content"].startswith("📝")
