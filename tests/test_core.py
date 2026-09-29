from datetime import date

from core.exporters import export_report
from core.research import (
    Source,
    rank_and_filter,
    resolve_period,
    synthesize_local,
)
from core.writing import _explicit_risk_facts, _grounded_summary, _source_excerpt
from core.writing import write_with_groq


def test_period_presets():
    start, end = resolve_period("Last 7 days", None, None)
    assert (end - start).days == 7


def test_custom_period_uses_exact_dates():
    start, end = resolve_period(
        "Custom", date(2024, 1, 10), date(2024, 3, 15)
    )
    assert start == date(2024, 1, 10)
    assert end == date(2024, 3, 15)


def test_rank_deduplicates_and_scores():
    sources = [
        Source("AI policy", "https://example.gov/ai", "AI policy evidence and implementation details.", "government", published_at="2026-09-20"),
        Source("AI policy duplicate", "https://example.gov/ai", "Duplicate", "web", published_at="2026-09-20"),
    ]
    ranked = rank_and_filter(sources, "AI policy", date(2026, 9, 1), date(2026, 9, 26))
    assert len(ranked) == 1
    assert ranked[0].credibility >= 80


def test_rank_excludes_irrelevant_and_undated_sources():
    sources = [
        Source("Dangote IPO risk", "https://example.com/one", "Investor risk", "news", published_at="2026-09-20"),
        Source("Unrelated Iran story", "https://example.com/two", "Middle East", "news", published_at="2026-09-20"),
        Source("Dangote IPO undated", "https://example.com/three", "Investor risk", "web"),
    ]
    ranked = rank_and_filter(
        sources, "Dangote IPO downsides", date(2026, 9, 1), date(2026, 9, 26)
    )
    assert [source.title for source in ranked] == ["Dangote IPO risk"]


def test_local_report_is_coherent_and_discloses_shortfall():
    sources = [
        Source(
            "Dangote IPO raises valuation questions - Example News",
            "https://example.com/valuation",
            "Investors are examining valuation risk and market liquidity.",
            "news",
            publisher="Example News",
            published_at="2026-09-20",
            credibility=65,
            credibility_label="Moderate",
        )
    ]
    report = synthesize_local(
        "Dangote IPO downsides",
        sources,
        ["Executive summary", "Key findings", "Detailed analysis", "Contradictions and limitations", "References"],
        date(2026, 9, 1),
        date(2026, 9, 26),
        25,
    )
    summary = report.split("## Executive summary", 1)[1].split("## Key findings", 1)[0]
    assert "example.com" not in summary
    assert "1 relevant, date-verified sources from the 25 requested" in summary
    assert "Source availability was below target" in report


def test_all_export_formats_are_nonempty():
    report = {"topic": "Test topic", "report_markdown": "# Test topic\n\n## Key findings\n\n- Evidence item."}
    for kind in ["PDF", "Word", "PowerPoint", "Markdown", "Text"]:
        data, filename, mime = export_report(report, kind)
        assert data
        assert "." in filename
        assert mime


def test_source_excerpt_reaches_risk_evidence_later_in_article():
    content = (
        "The company announced an offer to the public. "
        "Retail investors can subscribe through approved channels. "
        "The transaction is expected to close this month. "
        + "Background information about the company and its operations. " * 20
        + "Investors face liquidity risk and the prospectus does not establish a dividend history."
    )
    excerpt = _source_excerpt("Company IPO potential downsides", content)
    assert "liquidity risk" in excerpt
    assert "dividend history" in excerpt


def test_local_summary_uses_only_verified_facts():
    sources = [Source("Offer", "https://example.com", "", "news", publisher="News")]
    facts = [
        {"text": "The offer contains 4.1 billion shares.", "source_ids": [1]},
        {"text": "The article identifies liquidity risk for investors.", "source_ids": [1]},
    ]
    summary = _grounded_summary("Company IPO", facts, sources, 25)
    assert "4.1 billion shares" in summary
    assert "liquidity risk" in summary
    assert "over-saturation" not in summary
    assert "[1]" not in summary


def test_explicit_risk_facts_are_not_lost_when_model_omits_them():
    sources = [
        Source(
            "Offer analysis", "https://example.com", "", "news",
            content=(
                "The company described its plans for the public offer. "
                "Prospective investors must exercise caution because a share does not come "
                "with a guaranteed annual dividend."
            ),
        )
    ]
    facts = _explicit_risk_facts(sources)
    assert len(facts) == 1
    assert "guaranteed annual dividend" in facts[0]["text"]
    assert facts[0]["source_ids"] == [1]


def test_groq_writer_renders_structured_report(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            summary = (
                "The evidence describes a public offering and its terms without treating "
                "promotional forecasts as established outcomes. It identifies the size of "
                "the offer and the rights investors would acquire.\n\nThe available article "
                "also states that dividends are not guaranteed and that investors should "
                "evaluate the prospectus before making a decision."
            )
            return {"choices": [{"message": {"content": __import__("json").dumps({
                "executive_summary": summary,
                "key_findings": [{"text": "Dividends are not guaranteed.", "source_ids": [1]}],
                "detailed_analysis": [{"heading": "Investor considerations", "paragraphs": [{"text": "The prospectus should be reviewed.", "source_ids": [1]}]}],
                "limitations": [],
                "recommendations": [],
            })}}]}

    monkeypatch.setattr("core.writing.requests.post", lambda *args, **kwargs: Response())
    source = Source(
        "Offer analysis", "https://example.com/offer", "", "news",
        publisher="Example", published_at="2026-09-20",
        content="The prospectus should be reviewed. Dividends are not guaranteed.",
    )
    report = write_with_groq(
        "Company IPO", [source], ["Executive summary", "Key findings", "Detailed analysis", "References"],
        date(2026, 9, 1), date(2026, 9, 29), 1, "test-key", "openai/gpt-oss-20b",
    )
    assert "Dividends are not guaranteed. [1]" in report
    assert "https://example.com/offer" in report.split("## References", 1)[1]
    assert "https://example.com/offer" not in report.split("## References", 1)[0]
