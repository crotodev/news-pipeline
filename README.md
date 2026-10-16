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

Per-service tests:

```bash
docker build --target test -t news-streamer-test services/news-streamer && docker run --rm news-streamer-test
docker build --target test -t news-scraper-test services/news-scraper && docker run --rm news-scraper-test
cd services/news-model-api && .venv/Scripts/python -m pytest
```
