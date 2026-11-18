"""Report exact-span/type metrics on the generated, labelled synthetic corpus."""

import json
from collections import defaultdict
from pathlib import Path

from anonymizer.dataset import generate
from anonymizer.detection import Detector
from anonymizer.documents import load_document


def benchmark(directory=Path("data/synthetic")):
    manifest = generate(directory)
    detector = Detector()
    totals = defaultdict(lambda: [0, 0, 0])
    documents = []
    for item in manifest:
        path = directory / item["filename"]
        source = load_document(path.read_bytes(), path.name)
        expected = {(e["start"], e["end"], e["kind"]) for e in item["entities"]}
        actual = {(e.start, e.end, e.kind) for e in detector.detect(source.text)}
        tp, fp, fn = len(expected & actual), len(actual - expected), len(expected - actual)
        documents.append(
            {"document": path.name, "language": item["language"], "tp": tp, "fp": fp, "fn": fn}
        )
        for name in ("overall", "language:" + item["language"]):
            totals[name] = [a + b for a, b in zip(totals[name], (tp, fp, fn))]
        for kind in {e[2] for e in expected | actual}:
            gold, predicted = (
                {e for e in expected if e[2] == kind},
                {e for e in actual if e[2] == kind},
            )
            counts = (len(gold & predicted), len(predicted - gold), len(gold - predicted))
            totals["type:" + kind] = [a + b for a, b in zip(totals["type:" + kind], counts)]
    scores = {}
    for group, (tp, fp, fn) in totals.items():
        scores[group] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else 0,
            "recall": tp / (tp + fn) if tp + fn else 0,
        }
    return {"documents": documents, "scores": scores}


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2))
