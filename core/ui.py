from __future__ import annotations

import streamlit as st


def inject_visuals() -> None:
    st.html(
        """
        <style>
        @keyframes astraFloat { 0%,100%{transform:translateY(0);opacity:.52} 50%{transform:translateY(-9px);opacity:.85} }
        @keyframes astraGlow { 0%,100%{filter:drop-shadow(0 0 10px rgba(139,92,246,.25))} 50%{filter:drop-shadow(0 0 25px rgba(139,92,246,.6))} }
        .astra-hero { position:relative; overflow:hidden; border:1px solid #35284f; border-radius:22px; padding:30px 32px; margin:4px 0 24px; background:radial-gradient(circle at 85% 10%,rgba(139,92,246,.24),transparent 33%),linear-gradient(135deg,#151020,#09080e); }
        .astra-hero:after { content:""; position:absolute; width:180px; height:180px; border-radius:50%; right:-75px; top:-85px; background:rgba(168,85,247,.2); filter:blur(30px); animation:astraFloat 5s ease-in-out infinite; }
        .astra-kicker { color:#a78bfa; letter-spacing:.16em; font-size:.72rem; font-weight:700; text-transform:uppercase; }
        .astra-hero h1 { margin:.4rem 0 .55rem; font-size:clamp(2rem,4vw,3.6rem); line-height:1.02; letter-spacing:-.055em; max-width:850px; }
        .astra-hero p { color:#b8b1c8; max-width:720px; margin:0; font-size:1rem; }
        .astra-dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:#a78bfa; margin-right:8px; animation:astraGlow 2.5s ease-in-out infinite; }
        .st-key-research_form, .st-key-report_panel { border-color:#34284d !important; box-shadow:0 18px 55px rgba(0,0,0,.22); }
        [data-testid="stMetric"] { background:linear-gradient(145deg,rgba(28,23,43,.88),rgba(16,13,25,.9)); border:1px solid #302643; padding:14px 16px; border-radius:14px; }
        [data-testid="stStatusWidget"] { border-color:#44315f; }
        button[kind="primary"] { box-shadow:0 8px 28px rgba(124,58,237,.28); }
        </style>
        """
    )


def hero(kicker: str, title: str, subtitle: str) -> None:
    st.html(
        f'<section class="astra-hero"><div class="astra-kicker"><span class="astra-dot"></span>{kicker}</div><h1>{title}</h1><p>{subtitle}</p></section>'
    )


def export_buttons(report: dict, key_prefix: str = "export") -> None:
    from core.exporters import export_report
    formats = ["PDF", "Word", "PowerPoint", "Markdown", "Text"]
    cols = st.columns(len(formats), gap="small", wrap=True)
    for index, file_type in enumerate(formats):
        data, filename, mime = export_report(report, file_type)
        cols[index].download_button(
            file_type,
            data=data,
            file_name=filename,
            mime=mime,
            icon=":material/download:",
            key=f"{key_prefix}_{file_type}",
            width="stretch",
        )

