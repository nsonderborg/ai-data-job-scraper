# AI & Data Job Scraper

Automated job pipeline that scrapes **8 Danish job sources** daily, filters for AI/ML and data roles in Greater Copenhagen, scores each posting with a local LLM, and writes results to a Notion database.

Built to solve a real problem: staying on top of the fast-moving AI & data job market across fragmented Danish job boards, startup platforms, and VC career pages without manually checking each site every day.

## How It Works

```
┌─────────────────────────────────────────────────────┐
│                   8 Job Sources                      │
│  Jobindex · LinkedIn · The Hub · PensionsJob         │
│  Politi · Forsvaret · VC Career Pages · VCC Jobs     │
└──────────────────────┬──────────────────────────────┘
                       │ raw postings
                       ▼
┌─────────────────────────────────────────────────────┐
│              3-Stage Filter Pipeline                 │
│  1. Geographic filter (CPH / Nordsjælland / Skåne)  │
│  2. Student/intern role exclusion                    │
│  3. AI & data domain keyword matching                │
└──────────────────────┬──────────────────────────────┘
                       │ filtered postings
                       ▼
┌─────────────────────────────────────────────────────┐
│          Cross-Source Deduplication                   │
│  Pass 1: Exact URL match                             │
│  Pass 2: Normalised title + fuzzy company matching   │
└──────────────────────┬──────────────────────────────┘
                       │ unique postings
                       ▼
┌─────────────────────────────────────────────────────┐
│           LLM Relevancy Scoring (Ollama)             │
│  Local llama3.2 scores each posting 1–5              │
│  against candidate profile                           │
│  Graceful degradation if Ollama is offline            │
└──────────────────────┬──────────────────────────────┘
                       │ scored postings
                       ▼
┌─────────────────────────────────────────────────────┐
│              Notion Database Writer                   │
│  URL-based dedup against existing entries             │
│  Properties: title, company, source, score,          │
│  match reason, deadline, pipeline status              │
└─────────────────────────────────────────────────────┘
```

## Scrapers

| Source | Method | What It Scrapes |
|--------|--------|-----------------|
| **Jobindex** | Embedded Stash JSON extraction | Denmark's largest job board — 30+ AI/data keyword searches |
| **LinkedIn** | Apify actor (API-based) | 19 search combinations across Copenhagen + remote Denmark |
| **The Hub** | Nuxt.js SSR HTML parsing | Nordic startup job board — 10 AI/data keywords |
| **PensionsJob** | Next.js/MUI grid parsing | Pension industry portal — keyword-filtered for data/AI roles |
| **Politi** | XML sitemap parsing | Danish police careers — postal code filtered (1000–3699) |
| **Forsvaret** | Next.js JSON payload decoding | Danish defence careers — workplace region filtered |
| **VC Career Pages** | Multi-ATS auto-detection | 15 Danish VC firms — Workable, Lever, Greenhouse, Teamtailor, generic HTML |
| **VCC Jobs** | Paginated HTML scraping | venturecapitalcareers.com — pre-filtered Copenhagen + Malmö |

All scraping is **HTTP-only** — no Selenium, no Playwright, no headless browsers.

## Filters

### Geographic Filter
Only postings in:
- **Region Hovedstaden** (Greater Copenhagen)
- **Nordsjælland** (Hillerød, Helsingør, Hørsholm, etc.)
- **Skåne / Southern Sweden** (Malmö, Lund, Helsingborg)
- **Remote** (within CET/CEST ±4h timezone)
- **No location specified** (benefit of the doubt — included)

### Student/Intern Exclusion
Regex patterns covering Danish, English, and German variants: studiejob, praktik, internship, trainee, werkstudent, etc.

### AI & Data Domain Keywords
Postings must match at least one keyword from a curated list covering:
- **AI/ML**: machine learning, deep learning, NLP, LLM, computer vision, MLOps, generative AI, agentic
- **Data**: data scientist, data engineer, analytics engineer, ETL, data warehouse, data pipeline
- **BI**: Power BI, Tableau, Looker, DAX, dashboards, business intelligence
- **Infrastructure**: Python, SQL, Spark, Airflow, Kafka, Snowflake, Databricks, cloud engineering

## LLM Scoring

Each posting is scored 1–5 by a local **Ollama** instance running `llama3.2`:

| Score | Meaning |
|-------|---------|
| **5** | Perfect fit — data scientist, ML engineer, AI engineer, MLOps |
| **4** | Strong fit — data analyst with ML scope, NLP engineer, data platform |
| **3** | Acceptable — general data analyst, BI developer, backend with data focus |
| **2** | Weak fit — pure frontend, generic IT support, no data/AI scope |
| **1** | Not a fit — student roles, HR, sales, completely unrelated |

Hard caps enforce that student/intern roles always score 1 and director/VP-level roles cap at 2, regardless of domain relevance.

If Ollama is offline, postings still get written to Notion with `score=0` for manual review.

## Deduplication

Two-pass strategy that catches duplicates across different job boards:

1. **URL match** — exact URL comparison (LinkedIn URLs stripped of tracking params first)
2. **Title + company match** — normalised title comparison with fuzzy company matching (strips legal suffixes like A/S, ApS, GmbH; uses substring containment so "ATP" matches "ATP Ejendomme A/S")

## Setup

### Prerequisites
- Python 3.12+
- [Ollama](https://ollama.ai) with `llama3.2` model pulled
- Notion integration with database access
- Apify account (free tier works) for LinkedIn scraping

### Installation

```bash
git clone https://github.com/nsonderborg/ai-data-job-scraper.git
cd ai-data-job-scraper

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API keys
```

| Variable | Required | Description |
|----------|----------|-------------|
| `NOTION_API_KEY` | Yes | Notion integration token |
| `NOTION_DATABASE_ID` | Yes | Target Notion database ID |
| `APIFY_API_TOKEN` | Yes | Apify API token for LinkedIn |
| `OLLAMA_URL` | No | Ollama endpoint (default: `http://localhost:11434/api/generate`) |
| `OLLAMA_MODEL` | No | Ollama model name (default: `llama3.2`) |

### Notion Database Schema

Create a Notion database with these properties:

| Property | Type |
|----------|------|
| Job Title | Title |
| Company | Text |
| Source | Select |
| Description & Match | Text |
| Relevancy Score | Number |
| Deadline | Date |
| Date Found | Date |
| Pipeline Status | Select (New / Reviewed / Applying / Applied / Dismissed) |
| URL | URL |

### Run

```bash
# Make sure Ollama is running with the model loaded
ollama pull llama3.2

# Full run — scrape, filter, score, write to Notion
python main.py

# Dry run — scrape, filter, score, print results (no Notion write)
python main.py --dry-run
```

## Project Structure

```
ai-data-job-scraper/
├── main.py                      # Pipeline orchestrator
├── scrapers/
│   ├── __init__.py              # JobPosting dataclass
│   ├── http.py                  # Shared session with retry + backoff
│   ├── jobindex.py              # Jobindex.dk (Stash JSON)
│   ├── pensionsjobs.py          # PensionsJob.dk (Next.js/MUI)
│   ├── politi.py                # Politi.dk (XML sitemap)
│   ├── forsvaret.py             # Forsvaret.dk (Next.js JSON)
│   ├── linkedin_apify.py        # LinkedIn via Apify
│   ├── thehub.py                # The Hub (Nuxt.js SSR)
│   ├── vc_careers.py            # 15 VC career pages (multi-ATS)
│   ├── venturecapitalcareers.py # VCC paginated listings
│   ├── location_filter.py       # Geographic filtering
│   └── filters.py               # Student + domain keyword filters
├── scoring/
│   └── relevancy.py             # Ollama LLM scoring
├── notiondb/
│   └── writer.py                # Notion API writer with dedup
├── config/
│   ├── settings.py              # Environment variable loading
│   └── logging_config.py        # Console + file logging
├── logs/                        # Runtime logs (gitignored)
├── .env.example                 # Template for environment variables
├── requirements.txt
└── README.md
```

## Tech Stack

- **Python 3.12** — main runtime
- **requests + BeautifulSoup4** — HTTP scraping and HTML parsing
- **lxml** — XML sitemap parsing
- **apify-client** — LinkedIn jobs via Apify actor
- **notion-client 2.2.1** — Notion database writes (pinned — v3 breaks the API)
- **Ollama + llama3.2** — local LLM for relevancy scoring
- **python-dotenv** — environment variable management

## License

MIT
