from core import db


def test_supabase_save_uses_cloud_record(monkeypatch):
    secrets = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "secret",
    }
    monkeypatch.setattr(db, "secret", lambda name, default="": secrets.get(name, default))
    captured = {}

    def fake_request(method, **kwargs):
        captured["method"] = method
        captured.update(kwargs)
        return []

    monkeypatch.setattr(db, "_supabase_request", fake_request)
    research_id = db.save_research({
        "topic": "Test", "date_mode": "Custom", "start_date": "2026-09-01",
        "end_date": "2026-09-29", "requested_sources": 10,
        "analyzed_sources": 4, "sections": ["References"], "sources": [],
        "report_markdown": "# Test", "synthesis_mode": "Groq synthesis",
        "elapsed_seconds": 1.2,
    })
    assert captured["method"] == "POST"
    assert captured["json"]["id"] == research_id
    assert captured["json"]["sections"] == ["References"]
    assert db.storage_backend() == "Supabase"
