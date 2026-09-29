import streamlit as st
import hmac

from core.db import init_db
from core.config import secret
from core.ui import inject_visuals


st.set_page_config(
    page_title="Astra Research",
    page_icon=":material/auto_awesome:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

app_password = secret("APP_PASSWORD")
if app_password and not st.session_state.get("authenticated", False):
    st.title("Astra Research")
    st.caption("Enter the private access password to continue.")
    with st.form("access_gate"):
        supplied_password = st.text_input("Password", type="password")
        unlock = st.form_submit_button("Unlock", type="primary", icon=":material/lock_open:")
    if unlock:
        if hmac.compare_digest(supplied_password, app_password):
            st.session_state.authenticated = True
            st.rerun()
        st.error("Incorrect password.", icon=":material/error:")
    st.stop()

init_db()
st.session_state.setdefault("latest_research_id", None)
st.session_state.setdefault("pending_topic", "")
inject_visuals()

pages = [
    st.Page("app_pages/research.py", title="Research", icon=":material/travel_explore:", default=True),
    st.Page("app_pages/history.py", title="History", icon=":material/history:"),
    st.Page("app_pages/settings.py", title="Settings", icon=":material/tune:"),
]

navigation = st.navigation(pages, position="top")
navigation.run()
