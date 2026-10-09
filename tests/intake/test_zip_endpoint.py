"""WhatsApp ZIP -> /intake/whatsapp-zip -> claims, over HTTP, with an oracle reader (no key needed)."""

import io
import pathlib
import sys
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHOTS = sorted((ROOT / "data" / "synthetic" / "screenshots").glob("claim_00[1-3].*"))


@pytest.fixture(scope="module")
def client():
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from fastapi.testclient import TestClient
    import app.main as main
    from app.services import extractor as ex

    class Fixed(ex.VisionProvider):
        name, is_mock = "fixed-test", True

        def extract_fields(self, image_bytes, filename):
            return ex.RawExtraction.from_dict({"amount": "300", "reference": "714627048281"}, "fixed-test", True)

    old = ex.get_default_provider()
    ex.set_default_provider(Fixed())
    yield TestClient(main.app)
    ex.set_default_provider(old)


def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("_chat.txt", f"[10/10/26, 4:12:30 PM] Ayesha Khan: <attached: {SHOTS[0].name}>\n")
        for p in SHOTS:
            z.writestr(p.name, p.read_bytes())
        z.writestr("voice-note.opus", b"OggS....")
    return buf.getvalue()


def test_zip_upload_returns_one_claim_per_picture_and_ignores_other_files(client):
    r = client.post("/intake/whatsapp-zip", files={"file": ("chat.zip", _zip())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == len(SHOTS) == 3
    assert body["claims"][0]["sender"] == "Ayesha Khan"
    assert body["claims"][0]["claim"]["reference"] == "714627048281"
    assert any("ignored" in w for w in body["warnings"])


def test_not_a_zip_is_a_clear_400(client):
    r = client.post("/intake/whatsapp-zip", files={"file": ("x.zip", b"hello")})
    assert r.status_code == 400 and "ZIP" in r.json()["detail"]
