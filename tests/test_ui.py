from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_review_changes_invalidate_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("ANONYMIZER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=60
    ).run()
    app.toggle(key="use_sample").set_value(True).run()
    next(b for b in app.button if b.label == "Anonymize").click().run()
    assert not app.error
    assert not app.exception
    assert len(app.get("download_button")) == 1
    next(b for b in app.button if b.label == "Reverse Anonymize").click().run()
    assert len(app.get("download_button")) == 2
    app.text_area(key="manual").set_value("Banque Démonstration").run()
    assert len(app.get("download_button")) == 0
    next(b for b in app.button if b.label == "Anonymize").click().run()
    assert not app.error
    assert "Banque Démonstration" not in app.session_state.anonymized.text
