# News Pipeline

A comprehensive, end-to-end data pipeline for scraping, processing, and analyzing news articles from multiple global news sources. This pipeline integrates web scraping, machine learning classification, sentiment analysis, and real-time streaming to provide actionable insights from news data.

## Overview

The News Pipeline automatically collects articles from major news outlets, classifies them by category and sentiment, and streams the results for downstream consumption. The system is designed to be scalable, modular, and easy to extend with new data sources and models.

### Key Features

- **Multi-source Web Scraping**: Crawls news from 13+ news outlets including CNN, BBC, Reuters, New York Times, and more
- **Text Classification**: Machine learning-based article classification
- **Sentiment Analysis**: Transformer-based sentiment scoring using fine-tuned models
- **Real-time Streaming**: Kafka integration for real-time data streaming
- **Multiple Sinks**: Support for JSON, MongoDB, and Kafka outputs
- **Containerized Deployment**: Models served via API with Gunicorn

## Pipeline Architecture

![Pipeline Diagram](docs/pipeline.png)

## Run end-to-end

Prerequisites: Docker Desktop, Python 3.11 (for the smoke test only).

```bash
git submodule update --init --recursive
docker compose up -d --build           # kafka, mongodb, model API, streamer
docker compose ps                      # wait for news-pipeline-model-api to be healthy

# Verify the whole flow with a synthetic article
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r scripts/requirements.txt
.venv/Scripts/python scripts/e2e_smoke.py

# Crawl real news into raw_news
docker compose --profile scrape run --rm news-scraper
```

Enriched articles are published to the `enriched_news` topic and written as Parquet to the `streamer-data` volume.

### Enable local Ollama analysis (optional)

The streamer can add a structured analysis of the entire extracted article body using a separately managed Ollama instance. It is disabled by default. Install [Ollama](https://ollama.com/download), choose a model that fits your RAM/VRAM, and replace `your-model:tag` with its actual name:

```powershell
ollama pull your-model:tag
# Run in another terminal if the Ollama app/service is not already serving:
ollama serve
```

Then recreate the streamer with analysis enabled:

```powershell
$env:OLLAMA_ENABLED = "true"
$env:OLLAMA_MODEL = "your-model:tag"
docker compose up -d --build news-streamer
```

Compose defaults to `http://host.docker.internal:11434` to reach Ollama on the Docker Desktop host. Override `OLLAMA_BASE_URL` for another reachable server. When running the streamer directly on the host, the default is `http://localhost:11434`. This stack does not start Ollama or download models.

Long articles are analyzed in segments and the observations are synthesized. This adds local CPU/GPU work and batch latency. The context budget is checked explicitly; oversized tokens or synthesis prompts produce an article error rather than a silently truncated result. Ollama failures are recorded in `llm_error`, and articles continue to Kafka/Parquet. Enriched records include `llm_analysis`, `llm_model`, `llm_inferred_at`, and `llm_error`; all four are null when disabled. See the [streamer setup and settings](services/news-streamer/README.md#optional-full-article-analysis-with-ollama) for all seven environment variables, context limits, and output fields.

To opt out, set `$env:OLLAMA_ENABLED = "false"` and run `docker compose up -d news-streamer` again.

Per-service tests:

```bash
docker build --target test -t news-streamer-test services/news-streamer && docker run --rm news-streamer-test
docker build --target test -t news-scraper-test services/news-scraper && docker run --rm news-scraper-test
py -3.11 -m venv services/news-model-api/.venv
services/news-model-api/.venv/Scripts/python -m pip install -r services/news-model-api/requirements.txt -r services/news-model-api/requirements-dev.txt
cd services/news-model-api && .venv/Scripts/python -m pytest
```

On macOS/Linux use `python3.11` and `.venv/bin/python` instead of `py -3.11` and `.venv/Scripts/python`.
