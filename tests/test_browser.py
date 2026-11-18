"""Real Chromium tests: Streamlit server, review, downloads, restart and upload."""

from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import expect
import pytest

from anonymizer.documents import load_document

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("browser-server")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    @contextmanager
    def running():
        env = {
            **os.environ,
            "ANONYMIZER_DATA_DIR": str(directory / "vault"),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
        with (directory / "server.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port)],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        pytest.fail("Streamlit failed to start; see temporary server.log")
                    try:
                        with urlopen(url + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    pytest.fail("Streamlit health check timed out")
                yield url
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    return running


def choose_sample(page, name):
    if not page.get_by_label("Use a sample document").is_checked():
        page.get_by_text("Use a sample document", exact=True).click()
    page.get_by_role("combobox", name="Sample document").click()
    page.get_by_role("option", name=name, exact=True).click()
    expect(page.get_by_role("button", name="Anonymize", exact=True)).to_be_visible(timeout=60000)


def save_download(page, label, path):
    with page.expect_download() as event:
        page.get_by_role("button", name=label, exact=True).click()
    event.value.save_as(path)
    assert path.stat().st_size > 100


def observe_browser(page):
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.on(
        "request",
        lambda request: (
            external.append(request.url)
            if request.url.startswith(("http:", "https:")) and "127.0.0.1" not in request.url
            else None
        ),
    )
    return errors, external


def test_upload_landing_layout(page, server, tmp_path):
    errors, external = observe_browser(page)
    page.set_viewport_size({"width": 1440, "height": 1000})
    with server() as url:
        page.goto(url)
        expect(page).to_have_title("Document Anonymizer", timeout=60000)
        expect(page.get_by_role("heading", name="Choose a document")).to_be_visible()
        expect(page.get_by_test_id("stFileUploader")).to_be_visible()
        expect(page.get_by_test_id("stSidebar")).to_have_count(0)
        expect(page.locator("#MainMenu")).to_have_count(0)
        expect(page.get_by_role("button", name="Clear session")).to_have_count(0)
        assert not page.get_by_label("Use a sample document").is_checked()
        reference = page.get_by_role("textbox", name="Document reference", exact=True)
        expect(reference).to_have_value("")
        expect(reference).to_have_css("color", "rgb(255, 255, 255)")
        expect(page.get_by_test_id("stApp")).to_have_css("background-color", "rgb(27, 31, 36)")
        assert page.get_by_test_id("stException").count() == 0
        page.screenshot(path=str(tmp_path / "landing-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        expect(reference).to_be_visible()
        expect(page.get_by_test_id("stFileUploader")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / "landing-mobile.png"))
        page.get_by_role("radiogroup", name="Operation", exact=True).get_by_text(
            "Reverse Anonymize", exact=True
        ).click()
        expect(page.get_by_role("heading", name="Restore a document")).to_be_visible()
        expect(page.get_by_text("Upload anonymized PDF or DOCX", exact=True)).to_be_visible()
    assert not errors
    assert not external


@pytest.mark.parametrize(
    "name",
    [
        "bank_statement_fr.pdf",
        "insurance_claim_fr.pdf",
        "onboarding_en.docx",
        "insurance_contract_mixed.docx",
    ],
)
def test_browser_roundtrip(page, server, tmp_path, name):
    errors, external = observe_browser(page)
    page.set_viewport_size({"width": 1440, "height": 1000})
    with server() as url:
        page.goto(url)
        expect(page).to_have_title("Document Anonymizer", timeout=60000)
        expect(page.get_by_role("heading", name="Document Anonymizer", exact=True)).to_be_visible()
        choose_sample(page, name)
        if name == "bank_statement_fr.pdf":
            page.screenshot(path=str(tmp_path / "review-desktop.png"), full_page=True)
        page.get_by_role("button", name="Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Anonymized preview")).to_be_visible(timeout=60000)
        assert page.get_by_test_id("stException").count() == 0
        anonymized = tmp_path / ("anonymized" + Path(name).suffix)
        save_download(page, "Download anonymized document", anonymized)
        page.get_by_role("button", name="Reverse Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Restored preview")).to_be_visible(timeout=30000)
        recovered = tmp_path / name
        save_download(page, "Download restored document", recovered)
        source = load_document((ROOT / "data/synthetic" / name).read_bytes(), name)
        assert load_document(recovered.read_bytes(), name).text == source.text
        page.get_by_role("heading", name="Restored preview").scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "desktop.png"))
        expect(page.get_by_test_id("stSidebar")).to_have_count(0)
        expect(page.locator("#MainMenu")).to_have_count(0)
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("heading", name="Restored preview").scroll_into_view_if_needed()
        if name.endswith(".pdf"):
            preview = page.get_by_test_id("stImage").last.locator("img")
            expect(preview).to_be_visible()
            # Wait for responsive layout, then check actual image bounds, not just page scroll width.
            page.wait_for_function("""() => {
                const images = document.querySelectorAll('[data-testid="stImage"] img');
                const rect = images[images.length - 1].getBoundingClientRect();
                return rect.width > 0 && rect.left >= 0 && rect.right <= window.innerWidth;
            }""")
        page.screenshot(path=str(tmp_path / "mobile.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.close()
    assert not errors
    assert not external


def test_restore_after_server_restart(browser, server, tmp_path):
    with server() as url:
        page = browser.new_page()
        page.goto(url)
        choose_sample(page, "bank_statement_fr.pdf")
        expect(page.get_by_role("button", name="Anonymize", exact=True)).to_be_visible(
            timeout=60000
        )
        page.get_by_role("button", name="Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Anonymized preview")).to_be_visible(timeout=60000)
        exported = tmp_path / "anonymized.pdf"
        save_download(page, "Download anonymized document", exported)
        page.close()
    with server() as url:
        page = browser.new_page()
        page.goto(url)
        expect(page.get_by_role("radio", name="Reverse Anonymize", exact=True)).to_be_visible(
            timeout=60000
        )
        page.get_by_role("radiogroup", name="Operation", exact=True).get_by_text(
            "Reverse Anonymize", exact=True
        ).click()
        uploader = page.get_by_test_id("stFileUploader").filter(
            has_text="Upload anonymized PDF or DOCX"
        )
        expect(uploader).to_be_visible()
        uploader.locator("input[type=file]").set_input_files(exported)
        page.get_by_role("button", name="Reverse Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Restored preview")).to_be_visible(timeout=60000)
        recovered = tmp_path / "restored.pdf"
        save_download(page, "Download restored document", recovered)
        assert "Camille Moreau" in load_document(recovered.read_bytes(), recovered.name).text
        page.close()


def test_upload_manual_and_errors(page, server, tmp_path):
    from docx import Document

    source = tmp_path / "manual.docx"
    doc = Document()
    doc.add_paragraph("Unlisted phrase for manual selection.")
    doc.save(source)
    with server() as url:
        page.goto(url)
        page.get_by_test_id("stFileUploader").locator("input[type=file]").set_input_files(source)
        expect(page.get_by_role("button", name="Anonymize", exact=True)).to_be_visible(
            timeout=60000
        )
        page.get_by_text("Add a missed value", exact=True).click()
        page.get_by_role("textbox", name="Manual values", exact=True).fill("Unlisted phrase")
        page.get_by_role("button", name="Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Anonymized preview")).to_be_visible(timeout=30000)
        result = tmp_path / "manual-anon.docx"
        save_download(page, "Download anonymized document", result)
        assert "[PERSON_" in load_document(result.read_bytes(), result.name).text
        # New uploaded input invalidates old previews and download state.
        invalid = tmp_path / "invalid.pdf"
        invalid.write_bytes(b"not a pdf")
        page.get_by_test_id("stFileUploader").locator("input[type=file]").set_input_files(invalid)
        expect(page.get_by_text("Invalid or damaged PDF file.", exact=True)).to_be_visible(
            timeout=30000
        )
        expect(page.get_by_role("button", name="Download anonymized document")).to_have_count(0)
        # Restoration with absent mappings is a visible, safe error.
        page.get_by_role("radiogroup", name="Operation", exact=True).get_by_text(
            "Reverse Anonymize", exact=True
        ).click()
        uploader = page.get_by_test_id("stFileUploader").filter(
            has_text="Upload anonymized PDF or DOCX"
        )
        expect(uploader).to_be_visible()
        page.get_by_role("textbox", name="Document reference", exact=True).fill("missing-case")
        page.get_by_role("textbox", name="Document reference", exact=True).press("Enter")
        uploader.locator("input[type=file]").set_input_files(result)
        expect(page.get_by_text("manual-anon.docx", exact=True)).to_be_visible()
        page.get_by_role("button", name="Reverse Anonymize", exact=True).click()
        expect(
            page.get_by_text(
                "No mappings exist for this case. Select the original case and key.", exact=True
            )
        ).to_be_visible(timeout=30000)


@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_rendered_upload_download_restore(page, server, tmp_path, kind):
    from test_rendered import complex_docx, complex_pdf

    source = tmp_path / ("complex." + kind)
    source.write_bytes(complex_pdf("combined") if kind == "pdf" else complex_docx())
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    with server() as url:
        page.goto(url)
        expect(page).to_have_title("Document Anonymizer", timeout=60000)
        page.get_by_test_id("stFileUploader").locator("input[type=file]").set_input_files(source)
        expect(page.get_by_text("Rendered-page mode:", exact=False)).to_be_visible(timeout=90000)
        if kind == "docx":
            expect(page.get_by_text("Downloads are PDF", exact=False)).to_be_visible()
        page.get_by_text("Add a missed value", exact=True).click()
        page.get_by_role("textbox", name="Manual values", exact=True).fill("Alice Johnson")
        page.get_by_role("button", name="Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Anonymized preview")).to_be_visible(timeout=90000)
        result = tmp_path / "rendered-anonymized.pdf"
        save_download(page, "Download anonymized document", result)
        assert "Alice Johnson" not in load_document(result.read_bytes(), result.name).text
        page.get_by_role("button", name="Reverse Anonymize", exact=True).click()
        expect(page.get_by_role("heading", name="Restored preview")).to_be_visible(timeout=90000)
        restored = tmp_path / "rendered-restored.pdf"
        save_download(page, "Download restored document", restored)
        assert (
            load_document(restored.read_bytes(), restored.name).text
            == load_document(source.read_bytes(), source.name).text
        )
        assert page.get_by_test_id("stException").count() == 0
        page.get_by_role("heading", name="Anonymized preview").scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "rendered-desktop.png"))
    assert not errors
