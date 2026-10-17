# Optional Ollama Full-Article Analysis Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add opt-in local Ollama analysis that reads the full extracted article text and adds structured LLM results to enriched news records without changing existing ONNX predictions.

**Architecture:** Keep the existing ONNX model API for sentiment and topic inference. Add an optional Ollama HTTP client to the Spark streamer, running per Spark partition like the current model API calls. Send the full normalized `text` field (not the summary/title fallback capped for ONNX); for articles larger than a configured chunk size, analyze every chunk and synthesize the chunk results into one final JSON analysis. Store the analysis as a JSON string plus model, timestamp, and error metadata in the enriched record. The feature is disabled by default and uses an externally managed Ollama instance addressable from both host and Docker deployments.

**Tech Stack:** Python 3.11, PySpark Structured Streaming, requests, Ollama HTTP API (`/api/chat` with JSON output format), Docker Compose.

---

## Decisions and boundaries

- Preserve current sentiment and topic ONNX flows unchanged.
- Make LLM analysis opt-in via `OLLAMA_ENABLED=false` by default.
- Use `text` (the extracted full article body) after whitespace normalization; never substitute the truncated `text_for_inference`.
- Use chunk-and-synthesize processing so all article text is considered when the article exceeds the configured chunk size. Bound chunk size and Ollama context via explicit settings; do not silently truncate.
- Default structured analysis fields: `summary`, `key_points`, `entities`, `sentiment`, and `caveats`. Parse and validate JSON; malformed or failed responses become per-article error metadata and must not stop other records.
- Do not bundle an Ollama model download or force a large Ollama container into the default Compose stack. The user runs Ollama locally or elsewhere and configures its reachable URL/model. On Windows Docker Desktop, the typical host URL is `http://host.docker.internal:11434`; for local non-container runs it is `http://localhost:11434`.
- Output fields are `llm_analysis` (JSON string), `llm_model`, `llm_inferred_at`, and `llm_error`. They are null when disabled, preserving a stable enriched-record shape.

## Task 1: Define settings and full-text preparation

**Files:**
- Modify: `services/news-streamer/stream.py`
- Modify: `services/news-streamer/config.yaml`
- Test: `services/news-streamer/tests/test_parsing.py`

**Step 1: Write failing tests**

Add tests proving that:
- The default setting disables Ollama.
- `text_for_llm` is based on full `text`, whitespace-normalized, and is not truncated by `MAX_INFER_CHARS`.
- Missing or blank article text yields a null/empty full-text value without changing ONNX `text_for_inference` fallback behavior.

**Step 2: Run the focused tests**

Run from `services/news-streamer`:

```powershell
python -m pytest tests/test_parsing.py -q
```

Expected: the new assertions fail because the setting and full-text column do not exist yet.

**Step 3: Implement configuration and preparation**

Add environment-backed settings with safe defaults:
- `OLLAMA_ENABLED=false`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL` (required only when enabled; no assumed heavyweight model)
- `OLLAMA_TIMEOUT_S=180`
- `OLLAMA_CHUNK_CHARS=6000`
- `OLLAMA_NUM_CTX=8192`
- `OLLAMA_KEEP_ALIVE=5m`

Add a separate `text_for_llm` column from full `text`, normalized only for whitespace. Keep `text_for_inference` behavior and its character limit as-is. Add LLM result schema fields so disabled runs produce null-valued result metadata.

**Step 4: Re-run the focused tests**

Run: `python -m pytest tests/test_parsing.py -q`

Expected: PASS.

## Task 2: Implement Ollama full-article client and chunk synthesis

**Files:**
- Create: `services/news-streamer/ollama_client.py`
- Test: `services/news-streamer/tests/test_ollama_client.py`

**Step 1: Write failing client tests**

Cover:
- One Ollama request for an article within the chunk limit.
- Multiple chunk-analysis requests plus one synthesis request for a longer article.
- Request uses configured model, `/api/chat`, JSON format, temperature 0, configured context, and timeout.
- Valid result parsing and required-field validation.
- Empty text, HTTP failure, Ollama error payload, malformed JSON, and missing fields return an error result for that article.
- Results retain the original `url_hash` so Spark can join them deterministically.

Mock HTTP; tests must not require Ollama to be installed or running.

**Step 2: Run the focused tests**

Run: `python -m pytest tests/test_ollama_client.py -q`

Expected: FAIL because the client is not implemented.

**Step 3: Implement the client**

Use the standard library plus the existing `requests` dependency. Implement:
- Text chunking on whitespace boundaries with no dropped characters/words.
- A per-chunk prompt that requests evidence-grounded structured observations and forbids invented facts.
- A final synthesis prompt that combines all chunk observations into the agreed output schema.
- Single-request handling for short articles.
- Response parsing, schema validation, timestamps, and per-item error capture.
- A Spark `mapPartitions` adapter that batches outgoing article records but processes each article independently; use one HTTP session per partition and never fail the whole partition for one model response.

Do not log full article text or prompts.

**Step 4: Re-run the focused tests**

Run: `python -m pytest tests/test_ollama_client.py -q`

Expected: PASS.

## Task 3: Add optional LLM analysis to the streaming enrichment flow

**Files:**
- Modify: `services/news-streamer/stream.py`
- Modify: `services/news-streamer/api_client.py` only if sharing small partition-row helpers is cleaner; avoid coupling Ollama to ONNX endpoint contracts.
- Test: `services/news-streamer/tests/test_batch_writer.py`
- Test: `services/news-streamer/tests/test_kafka_sink.py` (or relevant current sink test)

**Step 1: Write failing flow tests**

Verify that:
- When disabled, no Ollama call occurs and output fields are null.
- When enabled, the streamer sends `text_for_llm`, joins LLM results by `url_hash`, and retains all existing ONNX output fields.
- A per-article Ollama error is recorded while the article still reaches sinks.
- Kafka JSON includes all four LLM fields, with explicit nulls when disabled.

**Step 2: Run the focused tests**

Run: `python -m pytest tests/test_batch_writer.py tests/test_kafka_sink.py -q`

Expected: new assertions fail before wiring is added.

**Step 3: Wire the optional call into `foreachBatch`**

Add `call_ollama_analysis` parallel to existing sentiment/classification functions. Pass full text, configured model, URL, limits, context, and timeout. Join LLM results to the enriched DataFrame on `url_hash`. Skip the HTTP work entirely when disabled while adding null-valued schema columns. Include LLM failures in batch error counts/logs without logging content.

**Step 4: Re-run the focused tests**

Run: `python -m pytest tests/test_batch_writer.py tests/test_kafka_sink.py -q`

Expected: PASS.

## Task 4: Configure Docker and document local setup

**Files:**
- Modify: `docker-compose.yml`
- Modify: `services/news-streamer/config.yaml`
- Modify: `services/news-streamer/README.md`
- Modify: root `README.md` if it documents the end-to-end Compose workflow.

**Step 1: Add configuration documentation**

Document opt-in configuration, model selection, local Ollama startup/model pull, host-versus-container base URLs, context/chunk tradeoffs, additional latency and compute cost, and how to disable the feature.

**Step 2: Pass settings into the streamer container**

Add environment passthrough for the Ollama settings. Keep analysis disabled by default. Use `http://host.docker.internal:11434` as the Compose host default, which the user can override with `OLLAMA_BASE_URL`. Do not make streamer startup depend on Ollama readiness when the feature is disabled; when enabled, fail clearly on configuration errors and isolate request failures per article.

**Step 3: Check Compose configuration**

Run from repository root:

```powershell
docker compose config -q
```

Expected: exit code 0.

**Step 4: Review the documentation and configuration diff**

Confirm documented values match actual environment names and defaults, and that no Ollama model is downloaded automatically.

## Task 5: Run submodule checks and complete repository handoff

**Files:**
- Verify changes in: `services/news-streamer` submodule
- Verify root pointer and orchestration changes in the repository root

**Step 1: Run streamer checks**

From `services/news-streamer`, run:

```powershell
python -m pytest -q
pre-commit run --all-files
```

Expected: all streamer tests and configured hooks pass.

**Step 2: Run root Compose validation**

From repository root, run `docker compose config -q`.

Expected: exit code 0.

**Step 3: Review serialized output compatibility**

Check that Parquet carries the new columns and Kafka JSON includes the four new fields, without dropping existing fields.

**Step 4: Commit with submodule boundaries respected**

Commit streamer code inside `services/news-streamer` first. Then commit the updated submodule pointer and root Compose/docs changes from the root repository. Keep both commits reviewable and scoped.

---

## End-to-end acceptance

1. With Ollama disabled (default), existing ONNX enrichments and sink output work without contacting Ollama; LLM fields are null.
2. With Ollama enabled and reachable, an article shorter than the chunk threshold gets one structured analysis based on its complete body text.
3. An article longer than the chunk threshold has every text chunk analyzed and those observations synthesized; no article suffix is silently discarded.
4. A failing Ollama response yields `llm_error` for that article and does not prevent other articles or sinks from completing.
5. Output records preserve existing fields and include the four LLM fields.
