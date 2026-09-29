import os

import streamlit as st

from core.db import DB_PATH, list_researches, storage_backend
from core.ui import hero


def configured(name: str) -> bool:
    if os.getenv(name):
        return True
    try:
        return bool(st.secrets.get(name, ""))
    except Exception:
        return False


hero("System configuration", "Tune the research engine.", "Astra runs without paid services. Add providers when you want broader discovery and stronger narrative synthesis.")

left, right = st.columns(2)
with left.container(border=True, height="stretch"):
    st.subheader("Search provider", anchor=False)
    if configured("TAVILY_API_KEY"):
        st.badge("Tavily connected", color="green", icon=":material/check:")
    else:
        st.badge("Public search mode", color="violet", icon=":material/public:")
    st.write("Public mode searches DuckDuckGo, Google News, Crossref, arXiv, and Open Library. Tavily adds a reliable, research-focused search layer.")
    st.caption("Recommended: Tavily when you need consistent 50–100 source runs.")

with right.container(border=True, height="stretch"):
    st.subheader("Synthesis provider", anchor=False)
    if configured("GROQ_API_KEY"):
        st.badge("Groq connected", color="green", icon=":material/check:")
    elif configured("OPENAI_API_KEY"):
        st.badge("OpenAI connected", color="green", icon=":material/check:")
    else:
        st.badge("Local synthesis mode", color="violet", icon=":material/memory:")
    st.write("Groq is the preferred cloud writer. When no hosted key is configured, Astra uses an installed Ollama model on this device.")
    st.caption("Recommended for deployment: Groq with openai/gpt-oss-20b.")

with st.expander("How to add API keys", icon=":material/key:"):
    st.code(
        'GROQ_API_KEY = "your-key"\nSUPABASE_URL = "https://your-project.supabase.co"\nSUPABASE_SECRET_KEY = "your-secret-key"\nAPP_PASSWORD = "choose-a-strong-password"',
        language="toml",
    )
    st.write("Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, add the services you want to use, then restart the app. The secrets file is excluded from Git.")

with st.container(border=True):
    st.subheader("Report storage", anchor=False)
    stats = st.columns(3)
    history = list_researches()
    stats[0].metric("Saved reports", len(history))
    backend = storage_backend()
    stats[1].metric("Database", backend)
    stats[2].metric("Storage", "Cloud" if backend == "Supabase" else "This device")
    if backend == "SQLite":
        st.caption(f"Database location: {DB_PATH}")

st.info("Source credibility scores are decision-support heuristics. Review original sources before relying on a report for medical, legal, financial, or safety-critical decisions.", icon=":material/shield:")
