"""Write missing local settings only. Does not start Docker, databases or AWS calls."""
import os
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parent
    path = root / ".env"
    if not path.is_file():
        raise SystemExit("Missing backend/.env")
    if not (root / "local-data/jumpit_all_v3/jobs.data.sql").is_file():
        raise SystemExit("Prepare jobs.data.sql first")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    existing = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            existing[key.strip()] = value.strip()
    settings = {"MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3308", "MYSQL_DATABASE": "career_matching",
                "MYSQL_USER": "career_runtime", "MYSQL_PASSWORD": secrets.token_hex(24),
                "MYSQL_ADMIN_PASSWORD": secrets.token_hex(24), "CHAT_API_TOKEN": secrets.token_hex(32),
                "CHAT_RUNTIME_ENABLED": "true", "CHAT_INCLUDE_UNVERIFIED": "true",
                "CHAT_RETENTION_HOURS": "24"}
    added = 0
    for key, value in settings.items():
        if existing.get(key):
            continue
        lines = [line for line in lines if line.partition("=")[0].strip() != key]
        lines.append(key + "=" + value)
        added += 1
    # Atomic replacement in the same directory; never print credentials.
    temporary = root / (".env.tmp-" + secrets.token_hex(8))
    try:
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"Local MySQL settings prepared ({added} missing keys added). No services started.")
    print("Local test retention: 24 hours by default; configure before production. Snapshots remain unverified.")


if __name__ == "__main__":
    main()
