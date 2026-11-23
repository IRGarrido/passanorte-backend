"""Create development secrets without printing or overwriting credentials.

Production must provision equivalent files through its secret manager.
"""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SERVICES = ("auth", "catalog", "validation", "gamification", "insights", "notifications", "chatbot")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("secrets"))
    args = parser.parse_args()
    root = args.directory
    if root.exists():
        parser.error("Destination already exists; refusing to replace persistent keys or passwords")
    root.mkdir(mode=0o700, parents=True)
    (root / "public").mkdir(mode=0o755)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    db_password, rabbit_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db_base = f"postgresql+psycopg://passanorte:{db_password}@db:5432/passanorte_"
    files = {
        "jwt-private.key": key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "public/key-1.pem": key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo),
        "pii.key": Fernet.generate_key(),
        "pii-hmac.key": secrets.token_urlsafe(48).encode(),
        "admin-password": secrets.token_urlsafe(32).encode(),
        "postgres-password": db_password.encode(),
        "rabbit-password": rabbit_password.encode(),
        "rabbit-url": f"amqp://passanorte:{rabbit_password}@rabbitmq:5672/".encode(),
        "database-template": (db_base + "{svc}").encode(),
        **{f"database-{svc}": (db_base + svc).encode() for svc in SERVICES},
    }
    for name, value in files.items():
        path = root / name
        with path.open("xb") as f:
            f.write(value)
        # Compose local secrets are bind mounts; non-root containers need read access.
        # The enclosing host directory is private (0700); production uses secret-manager ACLs.
        os.chmod(path, 0o444)
    print("Development secret files created. Credentials were not printed; protect the directory with host ACLs.")


if __name__ == "__main__":
    main()
