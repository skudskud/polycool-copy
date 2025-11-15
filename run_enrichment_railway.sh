#!/bin/bash
# One-time enrichment job to restore all events data

cd apps/subsquid-silo-tests/data-ingestion
python -m scripts.enrich_markets_events

