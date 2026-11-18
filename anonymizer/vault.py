"""Authenticated encrypted, atomically persisted case mappings."""

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock

from .errors import MappingError


class Vault:
    def __init__(self, directory=None):
        self.directory = Path(directory or os.environ.get("ANONYMIZER_DATA_DIR", ".local/vault"))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.lock = FileLock(str(self.directory / ".lock"), mode=0o600)
        with self.lock:
            configured = os.environ.get("ANONYMIZER_KEY")
            key_path = self.directory / "key.fernet"
            if configured:
                key = configured.encode("ascii")
            elif key_path.exists():
                key = key_path.read_bytes()
                key_path.chmod(0o600)
            else:
                if any(self.directory.glob("*.vault")):
                    raise MappingError(
                        "Encryption key is missing. Restore the original key from backup."
                    )
                key = Fernet.generate_key()
                self._atomic_write(key_path, key)
            try:
                self.cipher = Fernet(key)
            except (ValueError, TypeError):
                raise MappingError(
                    "Invalid encryption key. Configure a valid Fernet key."
                ) from None

    def _atomic_write(self, path, data):
        fd, temporary = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _path(self, case):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", case):
            raise MappingError("Case ID must contain 1-64 letters, digits, underscores or hyphens.")
        return self.directory / (hashlib.sha256(case.encode()).hexdigest() + ".vault")

    def _read(self, path):
        try:
            return json.loads(self.cipher.decrypt(path.read_bytes()))
        except (InvalidToken, ValueError, OSError):
            raise MappingError(
                "Cannot open mappings. Check the encryption key or restore a valid backup."
            ) from None

    def get(self, case):
        with self.lock:
            path = self._path(case)
            if not path.exists():
                raise MappingError(
                    "No mappings exist for this case. Select the original case and key."
                )
            return self._read(path)

    def assign(self, case, values):
        with self.lock:
            path = self._path(case)
            data = (
                self._read(path)
                if path.exists()
                else {
                    "version": 1,
                    "id": str(uuid.uuid4()),
                    "mapping": {},
                }
            )
            mapping = data["mapping"]
            inverse = {value: token for token, value in mapping.items()}
            for value, kind in values:
                if value not in inverse:
                    number = 1 + max(
                        (
                            int(t.rsplit("_", 1)[1][:-1])
                            for t in mapping
                            if t.startswith(f"[{kind}_")
                        ),
                        default=0,
                    )
                    token = f"[{kind}_{number:03d}]"
                    mapping[token] = value
                    inverse[value] = token
            self._atomic_write(
                path, self.cipher.encrypt(json.dumps(data, ensure_ascii=False).encode())
            )
            return data
