"""Create ignored Docker configuration using a fresh local-only credential."""
from pathlib import Path
import secrets

destination = Path(__file__).resolve().parents[1] / ".env"
if destination.exists():
    print("Existing .env preserved.")
else:
    destination.write_text(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n", encoding="utf-8")
    print("Created ignored .env for this local Docker demonstration.")
