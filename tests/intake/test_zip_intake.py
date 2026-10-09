import io
import zipfile

import pytest
from PIL import Image

from backend.app.intake.zip_intake import extract_images


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_only_real_images_are_taken_and_senders_are_read():
    chat = ("[10/10/26, 4:12:30 PM] Ayesha Khan: <attached: IMG-001.png>\n"
            "10/10/26, 4:15 pm - Rahul Sharma: IMG-002.png (file attached)\n")
    files = {"_chat.txt": chat, "IMG-001.png": _png(), "IMG-002.png": _png(), "notes.txt": "hello",
             "fake.jpg": "not really an image", "../evil.png": _png(), "clip.mp4": b"\x00\x00\x00\x18ftypmp42"}
    images, warnings = extract_images(_zip(files))
    assert [i["filename"] for i in images] == ["IMG-001.png", "IMG-002.png"]
    assert images[0]["sender"] == "Ayesha Khan" and images[1]["sender"] == "Rahul Sharma"
    assert warnings


def test_limits_and_bad_zip():
    with pytest.raises(ValueError):
        extract_images(b"this is not a zip")
    images, warnings = extract_images(_zip({f"IMG-{i:03d}.png": _png() for i in range(5)}), max_images=3)
    assert len(images) == 3 and any("more" in w for w in warnings)