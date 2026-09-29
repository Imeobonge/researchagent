from datetime import datetime

import streamlit as st

from core.db import get_research, list_researches
from core.ui import export_buttons, hero


hero("Local archive", "Your research, ready when you are.", "Every completed brief is stored privately on this machine and remains available for review or export.")

search = st.text_input("Search research history", placeholder="Search topics or report text…", icon=":material/search:")
items = list_researches(search)
if not items:
    st.info("No completed research matches this search.", icon=":material/inbox:")
    st.stop()

labels = {
    item["id"]: f'{item["topic"]}  ·  {datetime.fromisoformat(item["created_at"]).strftime("%d %b %Y, %H:%M")}'
    for item in items
}
selected_id = st.selectbox("Select a report", options=list(labels), format_func=labels.get)
report = get_research(selected_id)

with st.container(border=True):
    st.subheader(report["topic"], anchor=False)
    metrics = st.columns(4)
    metrics[0].metric(
        "Sources available",
        f'{report["analyzed_sources"]} / {report["requested_sources"]}',
    )
    metrics[1].metric("Window", report["date_mode"])
    metrics[2].metric("Created", datetime.fromisoformat(report["created_at"]).strftime("%d %b %Y"))
    metrics[3].metric("Synthesis", report["synthesis_mode"])
    if report["analyzed_sources"] < report["requested_sources"]:
        st.warning(
            f'Only {report["analyzed_sources"]} readable, relevant sources were '
            f'available from the {report["requested_sources"]} requested.',
            icon=":material/warning:",
        )
    export_buttons(report, f'history_{report["id"]}')

    with st.container(horizontal=True):
        if st.button("Research this topic again", icon=":material/replay:"):
            st.session_state.pending_topic = report["topic"]
            st.switch_page("app_pages/research.py")

    st.markdown(report["report_markdown"])
