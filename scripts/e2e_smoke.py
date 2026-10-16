"""End-to-end smoke test: raw_news -> streamer -> model API -> enriched_news.

Usage (stack must be running: `docker compose up -d --build`):
    python scripts/e2e_smoke.py [--bootstrap-servers localhost:9092] [--timeout 240]
"""

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaConsumer, KafkaProducer


def build_article() -> dict:
    url = f"https://smoke.test/{uuid.uuid4()}"
    text = (
        "Shares of the company soared after it reported record quarterly profits "
        "and raised its full-year outlook."
    )
    return {
        "title": "Company reports record profits",
        "author": "Smoke Test",
        "text": text,
        "summary": text,
        "url": url,
        "source": "smoke.test",
        "published_at": None,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url_hash": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    article = build_article()

    deadline = time.time() + args.timeout

    try:
        consumer = KafkaConsumer(
            "enriched_news",
            bootstrap_servers=args.bootstrap_servers,
            auto_offset_reset="latest",
            group_id=f"e2e-smoke-{uuid.uuid4()}",
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            consumer_timeout_ms=5000,
        )
    except Exception as exc:
        print(f"[smoke] FAIL: could not connect consumer: {exc}")
        return 1

    # Join the group and get partitions assigned before producing.
    while not consumer.assignment():
        if time.time() >= deadline:
            print(
                f"[smoke] FAIL: consumer not assigned partitions within {args.timeout}s "
                f"(is Kafka up at {args.bootstrap_servers}?)"
            )
            return 1
        consumer.poll(timeout_ms=1000)

    try:
        producer = KafkaProducer(
            bootstrap_servers=args.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        producer.send("raw_news", article).get(timeout=30)
        producer.flush()
    except Exception as exc:
        print(f"[smoke] FAIL: could not produce to raw_news: {exc}")
        return 1

    print(f"[smoke] produced url_hash={article['url_hash']}")
    while time.time() < deadline:
        for message in consumer:
            value = message.value
            if value.get("url_hash") != article["url_hash"]:
                continue
            print(f"[smoke] enriched: {json.dumps(value, indent=2)}")
            problems = []
            if not value.get("sentiment_label"):
                problems.append(f"sentiment missing: {value.get('sentiment_error')}")
            if not value.get("category_label"):
                problems.append(f"category missing: {value.get('category_error')}")
            if problems:
                print("[smoke] FAIL: " + "; ".join(problems))
                return 1
            print("[smoke] PASS")
            return 0

    print(f"[smoke] FAIL: no enriched message within {args.timeout}s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
