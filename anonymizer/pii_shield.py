"""Pinned PII Shield CLI adapter; document text and diagnostics are temporary."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import AnonymizerError

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.2.0"
CLI = ROOT / "node_modules/pii-shield/dist/cli/bin.mjs"
GUARD = ROOT / "scripts/pii_shield_offline.mjs"
SETUP = "Run python -m scripts.setup_pii_shield from the repository root."


def engine_directory():
    return Path(os.environ.get("ANONYMIZER_ENGINE_DIR", ROOT / ".local/pii-shield")).resolve()


def node_command():
    configured = os.environ.get("ANONYMIZER_NODE")
    local = ROOT / ".local/node/node_modules/node/bin/node"
    node = configured or (str(local) if local.is_file() else shutil.which("node"))
    if not node:
        raise AnonymizerError("PII Shield requires Node.js 22 or newer. See README installation.")
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
        major = int(result.stdout.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise AnonymizerError(
            "Cannot start Node.js. Check ANONYMIZER_NODE and installation."
        ) from None
    if result.returncode or major < 22:
        raise AnonymizerError("PII Shield requires Node.js 22 or newer. See README installation.")
    return node


def runtime_environment(directory):
    return {
        **os.environ,
        "NODE_OPTIONS": "",
        "PII_SHIELD_DATA_DIR": str(directory),
        "PII_SHIELD_MODELS_DIR": str(directory / "models"),
        "PII_SHIELD_MAPPINGS_DIR": str(directory / "mappings"),
        "PII_AUDIT_STDERR": "false",
        "PII_NER_LABEL_SET": os.environ.get("PII_NER_LABEL_SET", "tuned"),
        "PII_NER_THRESHOLD": os.environ.get("PII_NER_THRESHOLD", "0.20"),
        "PII_MIN_SCORE": os.environ.get("PII_MIN_SCORE", "0.20"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
    }


class Shield:
    def __init__(self):
        self.node = node_command()
        self.directory = engine_directory()
        try:
            package = json.loads((ROOT / "node_modules/pii-shield/package.json").read_text())
            ready = (self.directory / "ready").read_text().strip()
            if package["version"] != VERSION or ready != VERSION or not CLI.is_file():
                raise ValueError
            if not all((self.directory / name).is_dir() for name in ("models", "deps")):
                raise ValueError
        except (OSError, ValueError, KeyError):
            raise AnonymizerError("PII Shield is not installed or initialized. " + SETUP) from None

    def detect(self, text):
        # Do not send source filenames or document text through command-line arguments.
        with tempfile.TemporaryDirectory(prefix="anonymizer-detect-") as temporary:
            folder = Path(temporary)
            for name in ("models", "deps"):
                (folder / name).symlink_to(self.directory / name, target_is_directory=True)
            source = folder / "document.txt"
            source.write_text(text, encoding="utf-8")
            source.chmod(0o600)
            try:
                result = subprocess.run(
                    [
                        self.node,
                        "--import",
                        str(GUARD),
                        str(CLI),
                        "scan",
                        str(source),
                        "--json",
                        "--wait-ner",
                        "30",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=300,
                    env=runtime_environment(folder),
                    cwd=ROOT,
                )
                if result.returncode:
                    raise ValueError
                # 2.2.0's CLI can return success after NER failure. Check every
                # inference completed, rather than accepting a patterns-only result.
                server_log = (folder / "audit/server.log").read_text()
                ner_log = (folder / "audit/ner_init.log").read_text()
                started = server_log.count("[NER-Inference] BEFORE _gliner.inference()")
                completed = server_log.count("[NER-Inference] AFTER _gliner.inference()")
                if (
                    "[NER] GLiNER initialized" not in ner_log
                    or started == 0
                    or started != completed
                    or "[NER] Inference error:" in ner_log
                ):
                    raise ValueError
                payload = json.loads(result.stdout)
                if payload["char_count"] != len(text.encode("utf-16-le")) // 2:
                    raise ValueError
                return payload["entities"]
            except subprocess.TimeoutExpired:
                raise AnonymizerError(
                    "PII Shield exceeded its five-minute detection limit. Use a shorter document."
                ) from None
            except (OSError, ValueError, KeyError, TypeError):
                # Upstream stderr/diagnostics can contain input details; never echo them.
                raise AnonymizerError(
                    "PII Shield detection failed; no partial scan was accepted. " + SETUP
                ) from None
