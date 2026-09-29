# Astra Research

Astra is a Streamlit research agent that searches public internet sources, reads
the underlying articles, produces a cited research report, keeps report history,
and exports PDF, Word, PowerPoint, Markdown, and text files.

## Run locally

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Without cloud credentials, Astra stores history in `data/research.db` and uses a
locally installed Ollama model when available.

## Cloud configuration

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` for local
testing. Never commit `secrets.toml`.

```toml
GROQ_API_KEY = "gsk_..."
GROQ_MODEL = "openai/gpt-oss-20b"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
APP_PASSWORD = "a-long-private-password"
TAVILY_API_KEY = "" # optional
```

When both Supabase values are configured, cloud history is used automatically.
Otherwise, the app falls back to local SQLite. Groq is the preferred report
writer, followed by optional OpenAI, local Ollama, and finally an evidence digest.

## Create the Supabase table

1. Create a free Supabase project.
2. Open **SQL Editor** in its dashboard.
3. Run [`supabase/schema.sql`](supabase/schema.sql).
4. Copy the project URL and a server-side secret key into Streamlit secrets.

The schema enables row-level security and removes access from public database
roles. The secret key is used only by server-side Python and must never be placed
in source code or exposed to the browser.

## Deploy on Streamlit Community Cloud

1. Put this project in a GitHub repository.
2. Sign in at <https://share.streamlit.io> and choose **Create app**.
3. Select the repository and set the entrypoint to `streamlit_app.py`.
4. In **Advanced settings → Secrets**, paste the cloud configuration above.
5. Deploy and share the generated `streamlit.app` URL.

Set `APP_PASSWORD` before sharing the URL. Without it, every visitor can use the
research agent and view the shared report history.

## Storage and exports

- Cloud report history: Supabase when configured
- Local report history: `data/research.db`
- Downloads: generated in memory on request
