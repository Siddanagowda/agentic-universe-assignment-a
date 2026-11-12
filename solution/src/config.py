from pathlib import Path
import os
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "assignment-a-data" / "schemas"
DEFAULT_DB = ROOT / "au_assignment.sqlite3"


def get_fernet():
    key = os.getenv("AU_PII_KEY")
    if not key:
        # Local-development convenience. Set a stable AU_PII_KEY for durable use.
        key_file = ROOT / ".pii_key"
        if key_file.exists():
            key = key_file.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            key_file.write_text(key)
            try:
                key_file.chmod(0o600)
            except OSError:
                pass
    return Fernet(key.encode() if isinstance(key, str) else key)
