# Whole-section local embedding pilot

This pilot uses the jobs currently visible through `career-jobs-read`. It never changes that alias or the keyword search mappings, and does not write MySQL.

## Contract

- One job document, up to two vectors: the entire `qualifications` and entire `preferred_requirements` section.
- Empty sections are omitted. No sentence splitting, AI rewriting, or silent input truncation.
- GTE multilingual base, pinned ONNX conversion revision, int8 CPU artifact, CLS pooling and L2 normalization, 768 dimensions.
- 2,048-token deployment limit protects the shared host. Longer input fails explicitly. The model's 8,192-token architectural limit is not a capacity guarantee on this EC2.
- Source string ID, source version, whole section hashes, and model contract are preserved.
- A SQLite cache reuses public job-section embeddings. Resume queries are not cached or written into the job index.
- Candidate IDs and original sections are rechecked against the live ES copy. A selected job must still be fetched from MySQL by the existing service before assessment.

## Separate environment

```bash
python -m venv .venv-vector
.venv-vector/bin/pip install -r requirements-local.txt
.venv-vector/bin/python fetch_model.py --output /path/to/model
```

The download executes no Hugging Face Python model code. Checksums are stored in `manifest.json` and verified when loading the local artifact.

## Build, explicitly opt in

Run on the EC2 with access to its loopback-only ES, under a memory/CPU limit. A fresh pilot index is required; an existing index is not overwritten.

```bash
python pilot.py build --execute --model-dir /path/to/model --index career-job-vectors-pilot-example --limit 20 --cache /path/to/vectors.sqlite3
```

Omit `--limit` to process all current visible jobs. Deadline and status filters are applied. Source changes during processing stop publication and a later run can reuse the cache. No live alias is promoted.

## Resume search

```bash
python pilot.py search --model-dir /path/to/model --index career-job-vectors-pilot-example --resume-file /private/path/resume.txt --k 10
```

This prototype runs exact cosine searches separately for both fields. It merges by job ID and ranks by the larger section cosine as a transparent baseline; no tuned weights or qualification probability is claimed. Scores for the sections that retrieved each candidate are retained. Stale/deleted candidates are excluded against the live source copy. The whole resume is an ephemeral query, and no resume vector is stored in the public index.

Do not send raw resume content to stdout, telemetry, or a public cache. A web endpoint, ownership controls, rate limit, and existing job selection/assessment UI integration are subsequent work.

## Offline tests

```bash
python -m unittest discover -s . -p test_sections.py -v
```

## Scope and rollback

Pilot only, not an enabled end-user search path. Keyword search, the assessment dialogue, and outbox consumer are unchanged. The prototype uses a point-in-time index and checks source freshness at query time; automatic embedding outbox consumption is not yet implemented. To retire, stop the experiment, confirm no caller references its exact index, and explicitly remove only the separately named pilot artifacts. The tool never deletes the live index.

Sources:
- https://huggingface.co/Alibaba-NLP/gte-multilingual-base (upstream model, CLS/L2 instructions, Apache-2.0)
- https://huggingface.co/onnx-community/gte-multilingual-base (ONNX artifact)
- https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector
