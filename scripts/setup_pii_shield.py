"""Install PII Shield's local model/deps and verify a real offline NER scan."""

import os
import subprocess
import tempfile
from pathlib import Path

from filelock import FileLock

from anonymizer.errors import AnonymizerError
from anonymizer.pii_shield import (
    CLI,
    ROOT,
    VERSION,
    Shield,
    engine_directory,
    node_command,
    runtime_environment,
)


def setup():
    node = node_command()
    if not CLI.is_file():
        raise AnonymizerError("PII Shield CLI is missing. Run npm ci --ignore-scripts first.")
    directory = engine_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    environment = runtime_environment(directory)
    environment["PATH"] = str(Path(node).resolve().parent) + os.pathsep + os.environ.get("PATH", "")
    environment["npm_config_cache"] = str(directory / "npm-cache")
    with FileLock(str(directory / ".setup.lock"), mode=0o600):
        print(
            "Installing PII Shield model and inference dependencies (one-time download)…",
            flush=True,
        )
        try:
            subprocess.run(
                [node, str(CLI), "install-model", "--yes"],
                cwd=ROOT,
                env=environment,
                check=True,
                timeout=900,
            )
        except (OSError, subprocess.SubprocessError):
            raise AnonymizerError(
                "PII Shield setup failed. Check network access and npm installation."
            ) from None
        # install-model exits early when weights already exist. An ordinary scan
        # also repairs/warms inference dependencies before offline mode is enforced.
        with tempfile.TemporaryDirectory(prefix="anonymizer-setup-") as temporary:
            sample = Path(temporary) / "sample.txt"
            sample.write_text("John Smith works at Acme Corporation in New York.")
            try:
                subprocess.run(
                    [node, str(CLI), "scan", str(sample), "--json", "--wait-ner", "300"],
                    cwd=ROOT,
                    env=environment,
                    check=True,
                    timeout=600,
                    capture_output=True,
                )
            except (OSError, subprocess.SubprocessError):
                raise AnonymizerError(
                    "PII Shield inference dependencies could not be initialized."
                ) from None
        ready = directory / "ready"
        ready.write_text(VERSION + "\n")
        try:
            result = Shield().detect(
                "John Smith works at Acme Corporation. Our office is at "
                "42 Willow Lane, Bristol BS1 4QA."
            )
            if not any(e.get("reason", "").startswith("ner:gliner:") for e in result):
                raise AnonymizerError("PII Shield model loaded but the NER smoke test failed.")
        except Exception:
            ready.unlink(missing_ok=True)
            raise
        print("PII Shield is ready. Offline model inference verified.", flush=True)


if __name__ == "__main__":
    try:
        setup()
    except AnonymizerError as error:
        raise SystemExit(str(error)) from None
