from datetime import date, timedelta

import streamlit as st

from core.db import get_research, save_research
from core.research import SECTION_OPTIONS, resolve_period, run_research
from core.ui import export_buttons, hero


hero(
    "Intelligence workspace",
    "Research with depth, not noise.",
    "Search across the open web, current news, academic literature, books, and public institutions—then turn the evidence into a structured report.",
)

with st.container(border=True, key="research_form"):
    st.subheader("Start a research brief", anchor=False)
    date_mode = st.segmented_control(
        "Research window",
        ["Last 7 days", "Last year", "Custom"],
        default="Last year",
        key="date_mode",
    )

    if date_mode == "Custom":
        dates = st.columns(2)
        custom_start = dates[0].date_input(
            "Start date",
            value=date.today() - timedelta(days=30),
            max_value=date.today(),
            key="custom_start_date",
        )
        custom_end = dates[1].date_input(
            "End date",
            value=date.today(),
            min_value=custom_start,
            max_value=date.today(),
            key="custom_end_date",
        )
        st.caption(
            f"Only sources published from {custom_start:%d %b %Y} through "
            f"{custom_end:%d %b %Y} will be analyzed."
        )
    else:
        custom_start = None
        custom_end = None

    with st.form("research_request"):
        topic = st.text_area(
            "Research topic",
            value=st.session_state.pop("pending_topic", ""),
            placeholder="e.g. How is generative AI changing clinical drug discovery?",
            height=105,
            key="research_topic",
        )
        row = st.columns([1, 1], vertical_alignment="bottom")
        with row[0]:
            source_limit = st.select_slider(
                "Sources to analyze", options=[10, 25, 50, 100], value=25
            )
        with row[1]:
            st.caption("Broad discovery · credibility scoring · duplicate removal")

        sections = st.pills(
            "Report sections",
            SECTION_OPTIONS,
            default=SECTION_OPTIONS,
            selection_mode="multi",
        )
        submitted = st.form_submit_button(
            "Begin research", type="primary", icon=":material/rocket_launch:", width="stretch"
        )

if submitted:
    topic = topic.strip()
    if len(topic) < 5:
        st.error("Enter a more specific research topic.", icon=":material/error:")
        st.stop()
    if not sections:
        st.error("Select at least one report section.", icon=":material/error:")
        st.stop()
    start_date, end_date = resolve_period(date_mode, custom_start, custom_end)
    if start_date > end_date:
        st.error("The start date must be before the end date.", icon=":material/error:")
        st.stop()

    try:
        with st.status("Initializing research agent…", expanded=True) as status:
            def update(message: str) -> None:
                status.write(message)
            result = run_research(topic, source_limit, start_date, end_date, sections, update)
            status.update(label="Research complete", state="complete", expanded=False)
        payload = {
            **result,
            "date_mode": date_mode,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "requested_sources": result["requested_sources"],
            "analyzed_sources": len(result["sources"]),
            "sections": sections,
        }
        research_id = save_research(payload)
        st.session_state.latest_research_id = research_id
        st.toast("Report saved to your local history", icon=":material/check_circle:")
    except Exception as exc:
        st.error(str(exc), icon=":material/error:")

report = get_research(st.session_state.latest_research_id) if st.session_state.latest_research_id else None
if report:
    with st.container(border=True, key="report_panel"):
        stats = st.columns(4)
        stats[0].metric(
            "Sources available",
            f'{report["analyzed_sources"]} / {report["requested_sources"]}',
        )
        stats[1].metric("High credibility", sum(s["credibility_label"] == "High" for s in report["sources"]))
        stats[2].metric("Research time", f'{report["elapsed_seconds"]:.1f}s')
        stats[3].metric("Mode", report["synthesis_mode"])
        if report["analyzed_sources"] < report["requested_sources"]:
            missing = report["requested_sources"] - report["analyzed_sources"]
            st.warning(
                f'Only {report["analyzed_sources"]} readable, relevant sources '
                f'were available from the {report["requested_sources"]} requested '
                f'({missing} fewer than requested). The report explicitly reflects this limitation.',
                icon=":material/warning:",
            )
        export_buttons(report, "latest")
        st.markdown(report["report_markdown"])

    sources_panel = st.expander("Inspect source ledger", icon=":material/library_books:", on_change="rerun")
    if sources_panel.open:
        with sources_panel:
            rows = [{"Title": s["title"], "Type": s["source_type"].title(), "Publisher": s["publisher"],
                     "Published": s["published_at"] or "Unknown", "Credibility": s["credibility"], "URL": s["url"]}
                    for s in report["sources"]]
            st.dataframe(rows, hide_index=True, column_config={"URL": st.column_config.LinkColumn("Source")})
