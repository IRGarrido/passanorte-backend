"""Bootstrap local development; --reset-data discards this Compose project's volumes."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def bootstrap(*, reset_data: bool = False) -> None:
    # Compose is the source of truth for .env interpolation and host overrides.
    # Do not print its resolved configuration: it may contain sensitive values.
    compose = ("docker", "compose")
    config = json.loads(subprocess.check_output(
        (*compose, "config", "--format", "json"), cwd=ROOT,
    ))
    services = config["services"]
    if services["auth"]["environment"]["APP_ENV"] != "development":
        raise ValueError("This bootstrap is for APP_ENV=development only")
    secret_files = {name: Path(value["file"]) for name, value in config["secrets"].items()}
    directory = secret_files["postgres_password"].parent
    if not directory.exists():
        run(sys.executable, "scripts/generate_secrets.py", "--directory", str(directory))
    # Never replace part of a credential set: JWT/PII keys and paired broker
    # credentials must remain consistent. Validate before any destructive action.
    if any(not path.is_file() or path.stat().st_size == 0 for path in secret_files.values()):
        raise ValueError("Secret files are missing or empty; restore the complete credential directory")
    run(*compose, "config", "--quiet")
    if reset_data:
        # Explicitly opt in. Removing containers alone leaves passwords in volumes.
        run(*compose, "down", "--volumes")
    run(*compose, "up", "--build", "-d", "--wait", "--wait-timeout", "180")
    seed_command = services["seed"]["command"]
    email = seed_command[seed_command.index("--email") + 1]
    smoke = [
        sys.executable, "scripts/smoke_s2.py", "--email", email,
        "--url", services["auth"]["environment"]["EDGE_PUBLIC_URL"],
        "--ca", str(secret_files["edge_cert"]),
        "--password-file", str(secret_files["admin_password"]),
    ]
    if "chatbot" in services:
        smoke.append("--chatbot")
    run(*smoke)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-data", action="store_true",
        help="Delete this project's PostgreSQL/RabbitMQ volumes before startup; preserve secret files",
    )
    args = parser.parse_args()
    try:
        bootstrap(reset_data=args.reset_data)
    except subprocess.CalledProcessError:
        print("Bootstrap failed; subsequent steps were not executed.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError):
        print("Bootstrap failed; check Docker, development configuration and secret files.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
