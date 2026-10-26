# Personal Document Indexer — Design Spec

## Overview

A dedicated Node.js/TypeScript ingestion service (`doc-ingester`) that indexes personal email (Gmail) and SMS (iMessage) into Qdrant for RAG-powered search via OpenWebUI. Full historical backfill plus incremental sync. Deployed in `ai-services` namespace.

## Decisions

- **Full history**: Index all Gmail + all iMessage, not just forward-looking
- **Spam filtering**: Skip Gmail Promotions and Social categories, keep everything else
- **Auth**: Gmail App Password via IMAP (simple, works now)
- **Architecture**: Dedicated service (not n8n-native) for full control over chunking, metadata, dedup, and structured search
- **Query**: Both natural language Q&A (OpenWebUI RAG) and structured search/filters

## Data Model

### Qdrant Collection: `personal_docs`

- 768 dimensions, cosine distance
- Payload indexes on: `source_type`, `sender`, `thread_id`, `timestamp`, `labels`, `gmail_category`

### Hierarchical Metadata Per Vector

```json
{
  "source_type": "gmail | imessage",
  "account": "chris@gmail.com | iMessage",

  "thread_id": "string",
  "thread_subject": "string | null",
  "thread_participants": ["string"],
  "thread_message_count": 1,
  "thread_date_range": ["ISO8601", "ISO8601"],

  "message_id": "string",
  "sender": "string",
  "recipients": ["string"],
  "timestamp": "ISO8601",
  "labels": ["string"],
  "gmail_category": "string | null",
  "is_reply": false,
  "reply_depth": 0,

  "chunk_index": 0,
  "chunk_total": 1,
  "chunk_type": "full_message | paragraph | thread_segment",
  "text": "string"
}
```

### PostgreSQL Tracking: `doc_ingester_state`

| Column | Type | Purpose |
|--------|------|---------|
| source | text | "gmail" or "imessage" |
| message_id | text | unique ID from source |
| indexed_at | timestamptz | when processed |
| chunk_count | int | chunks generated |
| status | text | "indexed" or "failed" |

## Chunking Strategy

Message-aware semantic chunking, not fixed-size:

**Short messages (< 1000 chars)**: Single chunk, no splitting.

**Medium messages (1000-3000 chars)**: Split on paragraph boundaries (`\n\n`). If a paragraph exceeds 1000 chars, split on sentence boundaries. Each chunk gets message header prepended (from/to/subject/date) for standalone context.

**Long messages (3000+ chars)**: Thread-aware splitting — detect quoted reply markers (`>`, `On ... wrote:`, `------`), split into sub-messages first, then apply short/medium rules. Preserve reply chain metadata.

**Overlap**: Sentence-level — last sentence of chunk N becomes first sentence of chunk N+1.

**Email preprocessing**:
- Strip HTML to clean text (preserve links as `[text](url)`)
- Remove signatures (`--`, `Sent from my iPhone`, etc.)
- Strip repeated quoted threads (keep latest reply + one level of context)
- Log attachments in metadata but skip content

**iMessage preprocessing**:
- Group rapid-fire texts (< 5 min apart, same conversation) into single document before chunking

## Relevancy Scoring

Hierarchical metadata enables query-time relevancy beyond cosine similarity:

- **Thread importance**: Longer threads with more participants score higher
- **Recency weighting**: Timestamp-based boost for ambiguous queries
- **Sender frequency**: Cross-reference against thread count
- **Reply depth**: Originals and direct replies rank above nested forwards
- **Chunk type**: `full_message` chunks boosted over `paragraph` fragments
- **Thread reconstruction**: Pull full thread via `thread_id` for context

## Service Architecture

```
doc-ingester (Node.js/TypeScript)
├── src/
│   ├── connectors/
│   │   ├── gmail.ts          # IMAP client, poll/fetch, category filtering
│   │   └── imessage.ts       # HTTP endpoint receiving batches from Mac
│   ├── pipeline/
│   │   ├── preprocessor.ts   # HTML strip, signature removal, thread splitting
│   │   ├── chunker.ts        # Semantic chunking (short/medium/long rules)
│   │   ├── embedder.ts       # LocalAI embedding client
│   │   └── indexer.ts        # Qdrant upsert with hierarchical metadata
│   ├── storage/
│   │   ├── postgres.ts       # Indexing state tracking, dedup
│   │   └── qdrant.ts         # Collection management, payload indexes
│   ├── search/
│   │   └── queryService.ts   # Structured search + vector hybrid queries
│   ├── api/
│   │   ├── routes.ts         # POST /ingest/imessage, GET /search, GET /status
│   │   └── health.ts         # Health check
│   └── index.ts              # Entry point, connector scheduling
├── scripts/
│   └── imessage-sync.py      # Mac cron: reads chat.db, POSTs to service
├── Dockerfile
└── k8s/                      # Kustomize manifests
```

## Runtime Flow

1. **Gmail connector**: Runs every 5 min. First run fetches full history, subsequent runs pull new messages since last UID.
2. **iMessage sync**: Mac cron runs `imessage-sync.py` every 5 min, reads new rows from `~/Library/Messages/chat.db`, POSTs batches to doc-ingester endpoint.
3. **Pipeline**: preprocess → chunk → embed (LocalAI on Jetsons) → upsert (Qdrant).
4. **State tracking**: PostgreSQL records every message ID processed. Restart-safe, dedup-safe.
5. **Search**: Hybrid queries (vector similarity + structured metadata filters) via service endpoint. OpenWebUI queries Qdrant directly for RAG.

## Deployment

- **Namespace**: `ai-services`
- **Dependencies**: PostgreSQL (`database` ns), Qdrant (`vector-db` ns), LocalAI (`ai-services` ns)
- **Config**: Gmail app password + IMAP credentials in a Sealed Secret
- **Node**: `elitemini` (control plane) — no GPU needed, embedding calls go to Jetsons via LocalAI API

## Gmail Spam Filtering

IMAP `X-GM-LABELS` used to filter:
- **Skip**: `CATEGORY_PROMOTIONS`, `CATEGORY_SOCIAL`
- **Keep**: Primary, Updates, Forums, and any user-created labels
