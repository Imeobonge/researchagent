from __future__ import annotations

import concurrent.futures
import html
import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import requests
from lxml import html as lxml_html

from core.writing import evidence_digest, write_with_groq, write_with_ollama, write_with_openai
from core.config import secret


USER_AGENT = "AstraResearch/0.1 (personal research assistant)"
TIMEOUT = 14
SECTION_OPTIONS = [
    "Executive summary",
    "Key findings",
    "Detailed analysis",
    "Contradictions and limitations",
    "Recommendations",
    "References",
]

STOP_WORDS = {
    "about", "after", "against", "also", "and", "are", "could", "for",
    "from", "have", "into", "its", "it's", "more", "most", "potential",
    "should", "that", "the", "their", "this", "through", "what", "when",
    "where", "which", "with", "would",
}

RISK_THEMES = {
    "Competition and market concentration": {
        "monopoly", "competition", "dominance", "concentration", "antitrust",
        "market power", "pricing power",
    },
    "Valuation and investor risk": {
        "valuation", "overvalued", "investor", "return", "shares", "stock",
        "dividend", "liquidity", "risk", "downside", "loss",
    },
    "Debt, funding, and capital structure": {
        "debt", "loan", "leverage", "capital", "funding", "finance", "cost",
        "trillion", "billion",
    },
    "Operations and execution": {
        "operation", "production", "supply", "capacity", "delay", "execution",
        "maintenance", "feedstock", "crude", "refining",
    },
    "Regulation and governance": {
        "regulation", "regulatory", "governance", "disclosure", "oversight",
        "government", "policy", "compliance",
    },
}


@dataclass
class Source:
    title: str
    url: str
    snippet: str
    source_type: str
    publisher: str = ""
    published_at: str | None = None
    credibility: int = 50
    credibility_label: str = "Moderate"
    content: str = ""


def resolve_period(mode: str, custom_start: date | None, custom_end: date | None) -> tuple[date, date]:
    if mode == "Last 7 days":
        end = date.today()
        return end - timedelta(days=7), end
    if mode == "Last year":
        end = date.today()
        return end - timedelta(days=365), end
    if mode == "Custom":
        if custom_start is None or custom_end is None:
            raise ValueError("Choose both a start date and an end date.")
        return custom_start, custom_end
    raise ValueError(f"Unknown research window: {mode}")


def run_research(
    topic: str,
    source_limit: int,
    start_date: date,
    end_date: date,
    sections: list[str],
    progress: Callable[[str], None] | None = None,
) -> dict:
    started = time.perf_counter()
    notify = progress or (lambda _message: None)
    notify("Searching the open web, news, papers, books, and public institutions")

    tavily_key = _secret("TAVILY_API_KEY")
    per_channel = max(10, min(40, source_limit))
    news_queries = [
        topic,
        f'"{topic}" risks OR downsides OR concerns',
        f'"{topic}" analysis investors market competition',
    ]
    jobs: list[tuple[str, Callable[[], list[Source]]]] = [
        ("academic", lambda: search_crossref(topic, min(per_channel, 25), start_date, end_date)),
        ("academic", lambda: search_arxiv(topic, min(per_channel, 25), start_date, end_date)),
        ("news", lambda: search_news(news_queries[0], per_channel, start_date, end_date)),
        ("news", lambda: search_news(news_queries[1], per_channel, start_date, end_date)),
        ("news", lambda: search_news(news_queries[2], per_channel, start_date, end_date)),
        ("news", lambda: search_bing_news(topic, per_channel)),
        ("news", lambda: search_bing_news(f"{topic} risks concerns", per_channel)),
        ("books", lambda: search_books(topic, min(per_channel, 20))),
        ("government", lambda: search_duckduckgo(f"{topic} site:.gov", per_channel, "government")),
        ("web", lambda: search_duckduckgo(topic, per_channel, "web")),
        ("web", lambda: search_duckduckgo(f"{topic} risks downsides analysis", per_channel, "web")),
    ]
    if tavily_key:
        jobs.insert(0, ("web", lambda: search_tavily(topic, source_limit, tavily_key)))

    collected: list[Source] = []
    channel_errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(job): label for label, job in jobs}
        for future in concurrent.futures.as_completed(future_map):
            try:
                collected.extend(future.result())
            except Exception as exc:
                channel_errors.append(f"{future_map[future]}: {type(exc).__name__}")
                continue

    notify("Removing duplicates and checking publication dates")
    candidates = focus_source_cluster(
        rank_and_filter(collected, topic, start_date, end_date), topic
    )
    notify(f"Reading the underlying text from {min(len(candidates), source_limit * 3)} candidate sources")
    sources = enrich_sources(candidates[: source_limit * 3], source_limit)
    if not sources:
        raise RuntimeError(
            "No readable, date-verified sources were found. Try a wider date range or add Tavily in Settings."
        )

    available_count = len(sources)
    if available_count < source_limit:
        notify(
            f"Only {available_count} readable, relevant sources were available "
            f"for the requested {source_limit}"
        )
    notify(f"Synthesizing evidence from {available_count} sources")
    groq_key = _secret("GROQ_API_KEY")
    if groq_key:
        try:
            report = write_with_groq(
                topic, sources, sections, start_date, end_date, source_limit,
                groq_key, secret("GROQ_MODEL", "openai/gpt-oss-20b"),
            )
            synthesis_mode = "Groq synthesis"
        except Exception as exc:
            channel_errors.append(f"Groq synthesis: {type(exc).__name__}: {exc}")
            report = None
    else:
        report = None
    openai_key = _secret("OPENAI_API_KEY")
    if report is None and openai_key:
        try:
            report = write_with_openai(
                topic, sources, sections, start_date, end_date, source_limit, openai_key
            )
            synthesis_mode = "OpenAI synthesis"
        except Exception as exc:
            channel_errors.append(f"OpenAI synthesis: {type(exc).__name__}: {exc}")
            report = None
    if report is None:
        try:
            report = write_with_ollama(topic, sources, sections, start_date, end_date, source_limit)
            synthesis_mode = "Local AI synthesis"
        except Exception as exc:
            channel_errors.append(f"Local AI synthesis: {type(exc).__name__}: {exc}")
            report = evidence_digest(topic, sources, sections, start_date, end_date, source_limit)
            synthesis_mode = "Evidence digest (AI unavailable)"

    return {
        "topic": topic,
        "sources": [asdict(source) for source in sources],
        "report_markdown": report,
        "synthesis_mode": synthesis_mode,
        "requested_sources": source_limit,
        "available_sources": available_count,
        "source_shortfall": max(0, source_limit - available_count),
        "search_warnings": sorted(set(channel_errors)),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def _get(url: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    response = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response


def search_duckduckgo(query: str, limit: int, source_type: str) -> list[Source]:
    response = _get("https://html.duckduckgo.com/html/", params={"q": query})
    tree = lxml_html.fromstring(response.text)
    results: list[Source] = []
    for block in tree.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' result ')]")[:limit]:
        links = block.xpath(".//a[contains(concat(' ', normalize-space(@class), ' '), ' result__a ')]")
        if not links:
            continue
        link = links[0]
        raw_url = link.get("href", "")
        parsed = urlparse(raw_url)
        url = unquote(parse_qs(parsed.query).get("uddg", [raw_url])[0])
        snippets = block.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' result__snippet ')]")
        snippet = " ".join(snippets[0].text_content().split()) if snippets else ""
        results.append(
            Source(
                title=" ".join(link.text_content().split()),
                url=url,
                snippet=snippet,
                source_type=source_type,
                publisher=urlparse(url).netloc.removeprefix("www."),
            )
        )
    return results


def search_news(topic: str, limit: int, start: date, end: date) -> list[Source]:
    query = f'{topic} after:{start.isoformat()} before:{(end + timedelta(days=1)).isoformat()}'
    xml = _get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ).content
    root = ElementTree.fromstring(xml)
    results: list[Source] = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title", "Untitled")
        publisher = title.rsplit(" - ", 1)[-1] if " - " in title else "Google News"
        published = _parse_rfc_date(item.findtext("pubDate", ""))
        results.append(
            Source(title=title, url=item.findtext("link", ""), snippet=title,
                   source_type="news", publisher=publisher, published_at=published)
        )
    return results


def search_bing_news(topic: str, limit: int) -> list[Source]:
    xml = _get(
        "https://www.bing.com/news/search",
        params={"q": topic, "format": "rss"},
        headers={"User-Agent": "Mozilla/5.0"},
    ).content
    root = ElementTree.fromstring(xml)
    results: list[Source] = []
    for item in root.findall(".//item")[:limit]:
        raw_url = item.findtext("link", "")
        direct_url = parse_qs(urlparse(raw_url).query).get("url", [raw_url])[0]
        publisher = urlparse(direct_url).netloc.removeprefix("www.")
        results.append(
            Source(
                title=clean_text(item.findtext("title", "")),
                url=direct_url,
                snippet=clean_text(item.findtext("description", "")),
                source_type="news",
                publisher=publisher,
                published_at=_parse_rfc_date(item.findtext("pubDate", "")),
            )
        )
    return results


def enrich_sources(candidates: list[Source], limit: int) -> list[Source]:
    """Count a source only when there is enough readable content to analyze."""
    selected: list[Source] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(read_source, source): source for source in candidates}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                source.content = future.result()
            except Exception:
                source.content = ""
    for source in candidates:
        if len(source.content) >= 180:
            selected.append(source)
        if len(selected) >= limit:
            break
    return selected


def focus_source_cluster(candidates: list[Source], topic: str) -> list[Source]:
    """Keep similarly named events from being merged into one report."""
    qualifiers = ("refinery", "fertilizer", "cement", "sugar", "petroleum")
    topic_lower = topic.lower()
    explicit = next((term for term in qualifiers if term in topic_lower), None)
    counts = Counter(
        term
        for source in candidates
        for term in qualifiers
        if term in source.title.lower()
    )
    focus = explicit or (counts.most_common(1)[0][0] if counts and counts.most_common(1)[0][1] >= 2 else None)
    if not focus:
        return candidates
    filtered: list[Source] = []
    for source in candidates:
        title = source.title.lower()
        conflicting = any(term in title for term in qualifiers if term != focus)
        if focus in title or not conflicting:
            filtered.append(source)
    return filtered


def read_source(source: Source) -> str:
    if source.source_type == "academic" and len(source.snippet) >= 180:
        return clean_text(source.snippet)[:6000]
    if urlparse(source.url).netloc == "news.google.com":
        return ""
    response = _get(source.url, headers={"User-Agent": "Mozilla/5.0"})
    if "text/html" not in response.headers.get("content-type", ""):
        return ""
    if len(response.content) > 3_000_000:
        return ""
    tree = lxml_html.fromstring(response.content)
    for element in tree.xpath("//script|//style|//nav|//footer|//header|//aside|//form"):
        element.drop_tree()
    paragraphs = tree.xpath("//article//p|//main//p") or tree.xpath("//p")
    chunks: list[str] = []
    for paragraph in paragraphs:
        text = clean_text(paragraph.text_content())
        if len(text) >= 55 and text not in chunks:
            chunks.append(text)
    body = "\n".join(chunks)
    if len(body) < 180:
        descriptions = tree.xpath(
            "//meta[@name='description' or @property='og:description']/@content"
        )
        body = clean_text(" ".join(descriptions))
    return body[:8000]


def search_crossref(topic: str, limit: int, start: date, end: date) -> list[Source]:
    response = _get(
        "https://api.crossref.org/works",
        params={
            "query": topic,
            "rows": limit,
            "filter": f"from-pub-date:{start.isoformat()},until-pub-date:{end.isoformat()}",
            "select": "DOI,title,abstract,published,author,publisher,URL,type",
        },
    ).json()
    results: list[Source] = []
    for item in response.get("message", {}).get("items", []):
        title = (item.get("title") or ["Untitled paper"])[0]
        abstract = clean_text(item.get("abstract", ""))
        parts = (item.get("published") or {}).get("date-parts", [[]])[0]
        published = "-".join(str(value).zfill(2) for value in parts) if parts else None
        results.append(
            Source(title=title, url=item.get("URL", ""), snippet=abstract[:800] or title,
                   source_type="academic", publisher=item.get("publisher", "Crossref"),
                   published_at=published)
        )
    return results


def search_arxiv(topic: str, limit: int, start: date, end: date) -> list[Source]:
    xml = _get(
        "https://export.arxiv.org/api/query",
        params={"search_query": f"all:{topic}", "start": 0, "max_results": limit,
                "sortBy": "submittedDate", "sortOrder": "descending"},
    ).content
    root = ElementTree.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    results: list[Source] = []
    for entry in root.findall("a:entry", ns):
        published = entry.findtext("a:published", "", ns)[:10] or None
        if published and not (start.isoformat() <= published <= end.isoformat()):
            continue
        results.append(
            Source(title=" ".join(entry.findtext("a:title", "", ns).split()),
                   url=entry.findtext("a:id", "", ns),
                   snippet=" ".join(entry.findtext("a:summary", "", ns).split())[:900],
                   source_type="academic", publisher="arXiv", published_at=published)
        )
    return results


def search_books(topic: str, limit: int) -> list[Source]:
    docs = _get("https://openlibrary.org/search.json", params={"q": topic, "limit": limit}).json().get("docs", [])
    results: list[Source] = []
    for item in docs:
        key = item.get("key", "")
        authors = ", ".join(item.get("author_name", [])[:3])
        year = item.get("first_publish_year")
        results.append(
            Source(title=item.get("title", "Untitled book"),
                   url=f"https://openlibrary.org{key}" if key else "https://openlibrary.org",
                   snippet=f"Book by {authors or 'unknown author'}. First published {year or 'date unknown'}.",
                   source_type="books", publisher=item.get("publisher", ["Open Library"])[0],
                   published_at=f"{year}-01-01" if year else None)
        )
    return results


def search_tavily(topic: str, limit: int, key: str) -> list[Source]:
    response = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": topic, "search_depth": "advanced", "max_results": min(limit, 20),
              "include_answer": False, "include_raw_content": False},
        timeout=25,
    )
    response.raise_for_status()
    return [Source(title=item.get("title", "Untitled"), url=item.get("url", ""),
                   snippet=item.get("content", "")[:1000], source_type="web",
                   publisher=urlparse(item.get("url", "")).netloc.removeprefix("www."))
            for item in response.json().get("results", [])]


def rank_and_filter(sources: list[Source], topic: str, start: date, end: date) -> list[Source]:
    seen: set[str] = set()
    terms = _topic_terms(topic)
    ranked: list[tuple[float, Source]] = []
    for source in sources:
        canonical = _canonical_url(source.url)
        title_key = re.sub(r"\W+", "", source.title.lower())[:120]
        key = canonical or title_key
        if not source.url or not source.title or key in seen:
            continue
        seen.add(key)
        if not source.published_at:
            # A date range should be a real constraint, not a search suggestion.
            # Sources without a verifiable publication date are excluded.
            continue
        try:
            published = date.fromisoformat(source.published_at[:10])
            if published < start or published > end:
                continue
        except ValueError:
            continue
        score = credibility_score(source)
        source.credibility = score
        source.credibility_label = "High" if score >= 75 else "Moderate" if score >= 50 else "Limited"
        haystack = f"{source.title} {source.snippet}".lower()
        matched_terms = {term for term in terms if term in haystack}
        if not matched_terms:
            continue
        relevance = len(matched_terms) / max(1, len(terms))
        freshness = 0.1 if source.published_at else 0
        ranked.append((score / 100 + relevance * 1.5 + freshness, source))
    return [source for _, source in sorted(ranked, key=lambda pair: pair[0], reverse=True)]


def credibility_score(source: Source) -> int:
    domain = urlparse(source.url).netloc.lower()
    score = {"academic": 78, "government": 82, "books": 66, "news": 61, "web": 50}.get(source.source_type, 50)
    if domain.endswith(".gov") or ".gov." in domain:
        score += 12
    if domain.endswith(".edu") or "arxiv.org" in domain or "doi.org" in domain:
        score += 10
    if source.published_at:
        score += 4
    if len(source.snippet) > 180:
        score += 4
    return max(20, min(96, score))


def synthesize_local(
    topic: str,
    sources: list[Source],
    sections: list[str],
    start: date,
    end: date,
    requested_sources: int,
) -> str:
    high = sum(1 for source in sources if source.credibility_label == "High")
    types = Counter(source.source_type for source in sources)
    theme_sources = _group_sources_by_theme(sources)
    dominant_themes = [name for name, grouped in theme_sources.items() if grouped][:3]
    lines = [
        f"# {topic}",
        "",
        f"*Research window: {start:%d %b %Y} – {end:%d %b %Y} · "
        f"{len(sources)} of {requested_sources} requested sources available*",
        "",
    ]
    if "Executive summary" in sections:
        lines += ["## Executive summary", ""]
        lines.append(
            _executive_summary(topic, len(sources), requested_sources, dominant_themes)
        )
        lines.append("")
    if "Key findings" in sections:
        lines += ["## Key findings", ""]
        lines += _key_findings(sources, theme_sources)
        lines.append("")
    if "Detailed analysis" in sections:
        mix = ", ".join(f"{count} {kind}" for kind, count in types.most_common())
        lines += [
            "## Detailed analysis",
            "",
            f"The evidence base contains {mix}. {high} sources received a high "
            "credibility score. Findings below separate what the sources directly "
            "signal from what still requires verification.",
            "",
        ]
        rendered = False
        for theme, grouped in theme_sources.items():
            if not grouped:
                continue
            rendered = True
            lines += [f"### {theme}", "", _theme_analysis(theme, grouped, sources), ""]
        if not rendered:
            lines += [
                "### Evidence available",
                "",
                "The available material mainly reports that the event is taking place, "
                "but does not provide enough substantive detail to quantify its downsides. "
                "A defensible conclusion requires filings, audited financials, and the "
                "offer prospectus.",
                "",
            ]
    if "Contradictions and limitations" in sections:
        lines += ["## Contradictions and limitations", ""]
        if len(sources) < requested_sources:
            lines.append(
                f"- Source availability was below target: {len(sources)} relevant, "
                f"date-verified sources were found from {requested_sources} requested."
            )
        lines += [
            "- Headlines and search extracts can indicate a claim or concern, but they "
            "do not replace the underlying prospectus, audited accounts, or regulatory filings.",
            "- Positive statements from the company or interested parties should be "
            "treated as claims, not independent validation.",
            "- The report excludes undated material so the selected research window is enforced.",
            "- Credibility scores are transparent heuristics, not a substitute for expert review.",
            "",
        ]
    if "Recommendations" in sections:
        lines += ["## Recommendations", ""]
        lines += _recommendations_for_themes(dominant_themes)
        lines += [
            "- Read the offer prospectus and audited financial statements before making an investment decision.",
            "- Compare management claims with independent reporting and regulator disclosures.",
        ]
        if len(sources) < requested_sources:
            lines.append(
                "- Expand the date window or connect Tavily before treating this report as comprehensive."
            )
        lines.append("")
    if "References" in sections:
        lines += ["## References", ""]
        for index, source in enumerate(sources, 1):
            date_text = source.published_at or "date unavailable"
            lines.append(f"{index}. [{source.title}]({source.url}) — {source.publisher or source.source_type}; {date_text}; credibility {source.credibility}/100.")
    return "\n".join(lines).strip() + "\n"


def synthesize_openai(
    topic: str,
    sources: list[Source],
    sections: list[str],
    start: date,
    end: date,
    requested_sources: int,
    key: str,
) -> str:
    evidence = [{"id": i, "title": s.title, "url": s.url, "snippet": s.snippet,
                 "publisher": s.publisher, "date": s.published_at, "credibility": s.credibility}
                for i, s in enumerate(sources, 1)]
    prompt = f"""Write a rigorous research report in Markdown about: {topic}
Research window: {start.isoformat()} to {end.isoformat()}.
Source coverage: {len(sources)} relevant sources found from {requested_sources} requested.
Include only these sections: {', '.join(sections)}.
Write a coherent report, not a list of source titles. The executive summary must be
plain prose with no links, citations, reference numbers, or publisher names. In later
sections, cite claims with numbered Markdown links to the supplied evidence. Exclude
off-topic material. Distinguish evidence from inference, surface disagreements, state
the source shortfall plainly, and never invent facts. If snippets are too thin for a
claim, say that the evidence is insufficient instead of guessing.
Evidence JSON:\n{json.dumps(evidence, ensure_ascii=False)}"""
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "gpt-5-mini", "input": prompt}, timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    chunks = [part.get("text", "") for item in data.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text"]
    text = "\n".join(chunks).strip()
    if not text:
        raise RuntimeError("The model returned an empty report.")
    return text


def _best_sentences(snippets: list[str], topic: str, limit: int) -> list[str]:
    terms = set(re.findall(r"[a-z0-9]{4,}", topic.lower()))
    candidates: list[tuple[float, str]] = []
    seen: set[str] = set()
    for snippet in snippets:
        for sentence in re.split(r"(?<=[.!?])\s+", snippet):
            sentence = sentence.strip(" -\n")
            key = re.sub(r"\W+", "", sentence.lower())[:160]
            if len(sentence) < 45 or len(sentence) > 420 or key in seen:
                continue
            seen.add(key)
            words = re.findall(r"[a-z0-9]+", sentence.lower())
            overlap = sum(1 for word in words if word in terms)
            score = overlap * 3 + min(len(words), 45) / 20
            candidates.append((score, sentence))
    return [sentence for _, sentence in sorted(candidates, reverse=True)[:limit]]


def _topic_terms(topic: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", topic.lower())
        if token not in STOP_WORDS
    }


def _display_title(source: Source) -> str:
    title = clean_text(source.title)
    publisher = clean_text(source.publisher)
    suffix = f" - {publisher}"
    if publisher and title.lower().endswith(suffix.lower()):
        title = title[:-len(suffix)]
    return title.rstrip(" -")


def _group_sources_by_theme(sources: list[Source]) -> dict[str, list[tuple[int, Source]]]:
    grouped: dict[str, list[tuple[int, Source]]] = {theme: [] for theme in RISK_THEMES}
    for index, source in enumerate(sources, 1):
        haystack = f"{source.title} {source.snippet}".lower()
        for theme, keywords in RISK_THEMES.items():
            if any(keyword in haystack for keyword in keywords):
                grouped[theme].append((index, source))
    return grouped


def _executive_summary(
    topic: str,
    available: int,
    requested: int,
    themes: list[str],
) -> str:
    coverage = (
        f"This review found {available} relevant, date-verified sources from the "
        f"{requested} requested. "
    )
    if not themes:
        return (
            coverage
            + f"The available evidence confirms active reporting around {topic}, but it "
            "is too thin to support a confident assessment of the main risks. The most "
            "important unanswered questions concern valuation, financial obligations, "
            "governance, and execution. Primary filings are required before drawing an "
            "investment conclusion."
        )
    theme_text = ", ".join(theme.lower() for theme in themes[:-1])
    if len(themes) > 1:
        theme_text += f", and {themes[-1].lower()}"
    else:
        theme_text = themes[0].lower()
    return (
        coverage
        + f"The evidence clusters around {theme_text}. It shows that the subject is "
        "attracting both positive claims and material risk questions, but the public "
        "record in the selected window is not sufficient to quantify those risks. "
        "A sound decision therefore depends on primary filings, audited financials, "
        "offer terms, and independent regulatory evidence."
    )


def _key_findings(
    sources: list[Source],
    themes: dict[str, list[tuple[int, Source]]],
) -> list[str]:
    findings: list[str] = []
    for theme, grouped in themes.items():
        if not grouped:
            continue
        citations = ", ".join(f"[{index}]({source.url})" for index, source in grouped[:3])
        findings.append(
            f"- **{theme}:** {len(grouped)} source(s) raise or discuss this issue. "
            f"The evidence signals an area for due diligence rather than proving the "
            f"size of the risk. {citations}"
        )
    if not findings:
        for index, source in enumerate(sources[:5], 1):
            findings.append(
                f"- {_display_title(source)}. The available extract does not provide "
                f"enough detail to test the claim independently. [{index}]({source.url})"
            )
    return findings[:6]


def _theme_analysis(
    theme: str,
    grouped: list[tuple[int, Source]],
    all_sources: list[Source],
) -> str:
    examples = []
    for index, source in grouped[:3]:
        examples.append(f"[{_display_title(source)}]({source.url}) [{index}]")
    evidence = "; ".join(examples)
    return (
        f"{len(grouped)} of {len(all_sources)} sources touch on this theme. Relevant "
        f"coverage includes {evidence}. These items identify a due-diligence question, "
        "but the extracts available to the app do not quantify its probability or "
        "financial impact. That distinction matters: the evidence supports further "
        "investigation, not a definitive conclusion."
    )


def _recommendations_for_themes(themes: list[str]) -> list[str]:
    recommendations = {
        "Competition and market concentration": "- Test market-share and pricing assumptions against independent competition data.",
        "Valuation and investor risk": "- Stress-test valuation, liquidity, dividend, and downside scenarios under conservative assumptions.",
        "Debt, funding, and capital structure": "- Review debt covenants, refinancing needs, related-party obligations, and use of IPO proceeds.",
        "Operations and execution": "- Verify operating capacity, supply security, maintenance exposure, and execution milestones.",
        "Regulation and governance": "- Review governance rights, disclosures, regulatory approvals, and minority-shareholder protections.",
    }
    return [recommendations[theme] for theme in themes if theme in recommendations]


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    if any(marker in value for marker in ("â", "Ã", "Â")):
        try:
            value = value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _parse_rfc_date(value: str) -> str | None:
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _secret(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get(name, ""))
    except Exception:
        return ""
