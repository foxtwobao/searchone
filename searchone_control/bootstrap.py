"""Create local runtime secrets without touching upstream configuration."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def ensure_runtime_secrets(path: Path) -> tuple[bool, dict[str, str]]:
    if path.exists():
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return False, values

    values = {
        "SEARCHONE_MASTER_KEY": os.getenv("SEARCHONE_MASTER_KEY", "").strip()
        or Fernet.generate_key().decode("ascii"),
        "SEARCHONE_SESSION_SECRET": os.getenv("SEARCHONE_SESSION_SECRET", "").strip()
        or secrets.token_urlsafe(48),
        "SEARCHONE_ADMIN_USERNAME": os.getenv(
            "SEARCHONE_ADMIN_USERNAME", "admin"
        ).strip()
        or "admin",
        "SEARCHONE_ADMIN_PASSWORD": os.getenv("SEARCHONE_ADMIN_PASSWORD", "").strip()
        or secrets.token_urlsafe(18),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Generated locally. Keep this file private.\n"
        + "\n".join(f"{key}={value}" for key, value in values.items())
        + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    return True, values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    created, values = ensure_runtime_secrets(Path(args.path))
    print("created" if created else "existing")
    if created:
        print(f"admin_username={values['SEARCHONE_ADMIN_USERNAME']}")
        print(f"admin_password={values['SEARCHONE_ADMIN_PASSWORD']}")


if __name__ == "__main__":
    main()
