# Portable migration helpers

Start with [the handoff guide](../../docs/AWS_MIGRATION_HANDOFF.md) and [the teammate prompt](../../docs/MCP_MIGRATION_PROMPT.md).

- `capture_source.py`: full MySQL export from the existing EC2 to the local PC through token-protected loopback HTTP inside an encrypted SSM port-forwarding session. No S3 staging. Requires explicit source identity and `--confirm-full-export`.
- `portable_data.py`: typed JSONL/schema export, full checksum/record verification, empty-target MySQL restore with foreign-key verification, optional same-version Elasticsearch export/restore.
- `handoff.py`: safe unpack, committed-code package, destination identity check, nonsecret runtime config draft, explicitly requested private-bucket upload.
- `.env.example`: destination settings only, no working credentials.

These tools do not create a new AWS account, provision all services, grant model access or automatically restore the external vector runtime. A verified backup is not proof of successful restore/deployment. Keep all data and secrets outside Git.
