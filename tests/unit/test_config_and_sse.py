from app.config import Settings
from app.core.sse import format_sse


def test_sse_format_contains_event_and_json():
    event = format_sse("token", {"content": "你好"}, event_id="42")
    assert "id: 42" in event
    assert "event: token" in event
    assert "你好" in event
    assert event.endswith("\n\n")


def test_settings_parses_cors_origins():
    settings = Settings(cors_origins="http://a.test, http://b.test")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
