"""CLI script to create the database schema (run Alembic migrations)."""
import sys
import subprocess
from pathlib import Path

backend_dir = Path(__file__).parent.parent
result = subprocess.run(
    [str(backend_dir / ".venv/bin/alembic"), "upgrade", "head"],
    cwd=str(backend_dir),
)
sys.exit(result.returncode)

