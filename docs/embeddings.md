# Embedding documents

`manage.py embed_documents` converts decisions' documents to text,
splits the text into chunks and embeds each chunk. It chooses documents
from the database and writes its results next to each document, in
`LGSF_DATA_DIR` or the `lgsf-data-archive` bucket.

Each file goes through three stages:

1. **extract**: convert the file with Docling.
2. **chunk**: split it into chunks of up to 350 words, each with a
   header naming the council, decision and document.
3. **embed**: embed each chunk with Titan Text Embeddings V2 on Bedrock.

## Setup

```sh
uv sync --group embeddings
```

This installs Docling and CPU builds of torch, which the web servers
don't need. A plain `uv sync` removes them again.

To use a checkout of LGSF's data, set `LGSF_DATA_DIR=../LGSF/data` in
`.env`. Only the embed stage needs AWS credentials.

## Running it

```sh
uv run manage.py embed_documents MAN --since 2026-01-01 --dry-run
uv run manage.py embed_documents MAN --since 2026-01-01 --stages extract,chunk
AWS_PROFILE=dev-lgsf-dc uv run manage.py embed_documents MAN --since 2026-01-01
```

Council codes, `--since`, `--until`, `--document` and `--limit` choose
Documents as `import_decisions` does. `--help` lists the other options.

The unit of work is a file: a council's Documents with the same
`content_hash`. Each file is done once, at the storage key of its
earliest decision, and the results are copied to its other storage
keys.

On a Ryzen 9 7950X with the default 4 workers of 4 threads, extracting
and chunking took 1.2 seconds a page.

## What it writes

Next to each document:

| Suffix | Contents |
|---|---|
| `.docling.json` | The DoclingDocument, so chunks can be remade without converting again |
| `.md` | The text, as Markdown |
| `.chunks.jsonl` | `Chunk` records, one a line |
| `.titan-v2.jsonl` | `EmbeddingRecord`s for the chunks with `embed: true` |
| `.status.json` | Each stage's result. Written last. |

The format is worked out from the file's bytes, not its name. PDF,
DOCX, XLSX, PPTX, CSV, text and image files are converted. Files that
aren't converted only get a `status.json`, with an `extract.status` of:

| File | `extract.status` |
|---|---|
| ModernGov's "Reasons restricted" page | `restricted` |
| Any other HTML page, such as a logon page | `not_document` |
| An empty file | `empty` |
| Anything else, such as a ZIP | `unsupported` |

To remove everything it has written to a local data directory:

```sh
find "$LGSF_DATA_DIR" -path '*/Decisions/documents/*' \
  \( -name '*.pdf.*' -o -name '*.txt.*' \) -delete
```

## Running again

A run skips what `status.json` says is done, so it can be stopped and
started again.

- **Extract** runs once for each file. `--retry-failed` tries again
  files that `failed` or hit the `timeout`.
- **Chunk** runs again when its inputs change: the chunking settings,
  `CHUNKER_VERSION` in `chunking.py`, the Docling version, or the file's
  Documents and their decisions, such as a decision's title. Increase
  `CHUNKER_VERSION` when the chunking code or docling-core changes.
- **Embed** runs again when the chunks change, and only sends Bedrock
  the chunks whose text has changed.
- An error while chunking or embedding a file is recorded in its status,
  and the next run tries again.
- `--force` runs every stage again.

## Running on AWS Batch

`LGSFEmbeddingsBatch` (`cdk_stacks/stacks/embeddings_batch.py`) runs
the command on Spot instances, with the image built from
`Dockerfile.embeddings`. It's only in the development environment, and
is deployed by hand because the image is about 8GB:

```sh
AWS_PROFILE=dev-lgsf-dc DC_ENVIRONMENT=development \
  uv run --group cdk npx cdk deploy LGSFEmbeddingsBatch
```

It uses g6 or g5 GPU instances, or c7i or c7a.4xlarge with
`-c embeddings-instances=cpu`. To submit a run:

```sh
AWS_PROFILE=dev-lgsf-dc uv run manage.py embed_documents --remote --shards 20
```

`--remote` splits the files into shards of about the same size, uploads
them to `s3://lgsf-data-archive/embedding-runs/<run id>/`, and submits
an array job with a child for each shard. Each child writes its results
to the bucket. A child whose Spot instance is taken back is retried, and
skips the files already done. With `--dry-run`, the shards are written
to a local directory and the job is printed instead of submitted.

Follow a run with `aws logs tail /aws/batch/job --follow`. Afterwards,
`embed_documents --source s3 --dry-run` with the same filters shows
what's left.

Before the first run, check:

- `lgsf-data-archive` is publicly readable, so everything written to it
  is public.
- The quotas for G and VT instances in eu-west-2, which start at 0.
- The Bedrock quotas for Titan v2. `MAX_VCPUS` in the stack limits how
  many shards run at once.
