"""WhatsApp (or any messenger) 'export chat with media' ZIP -> the payment screenshots inside it.

Safety: images only (checked by file signature, not just the name), no path tricks, hard limits on file counts
and sizes (zip-bomb protection), nothing written to disk. The chat text file, if present, is used only to learn
who sent each picture; its text is never given to a model.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Dict, List, Tuple

MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_FILES_IN_ZIP = 2000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 150 * 1024 * 1024
DEFAULT_MAX_IMAGES = 25

_PNG, _JPEG = b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"
_FILE_IN_LINE = re.compile(r"([\w\-. ()]+\.(?:jpe?g|png))", re.I)


def _is_image(head: bytes) -> bool:
    return head.startswith(_PNG) or head.startswith(_JPEG)


def _chat_senders(text: str) -> Dict[str, Dict[str, str]]:
    """Best effort for the two common chat formats:
    '[10/10/26, 4:12:30 PM] Name: <attached: IMG-1.jpg>'  and  '10/10/26, 4:12 pm - Name: IMG-1.jpg (file attached)'."""
    out: Dict[str, Dict[str, str]] = {}
    for line in text.splitlines():
        m = _FILE_IN_LINE.search(line)
        if not m:
            continue
        head = line[: m.start()]
        if "] " in head:
            stamp, _, rest = head.partition("] ")
        elif " - " in head:
            stamp, _, rest = head.partition(" - ")
        else:
            stamp, rest = "", head
        out[m.group(1).strip().split("/")[-1]] = {"sender": rest.split(":")[0].strip()[:60],
                                                  "when": stamp.strip("[ ")[:40]}
    return out


def extract_images(data: bytes, max_images: int = DEFAULT_MAX_IMAGES) -> Tuple[List[Dict[str, object]], List[str]]:
    """Return ([{filename, bytes, sender?, when?}], warnings). Raises ValueError with a message for the user."""
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("The ZIP file is larger than 200 MB. Export fewer pictures or a shorter period.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This is not a valid ZIP file.")
    warnings: List[str] = []
    with zf:
        infos = sorted((i for i in zf.infolist() if not i.is_dir()), key=lambda i: i.filename)
        if len(infos) > MAX_FILES_IN_ZIP:
            raise ValueError(f"The ZIP has more than {MAX_FILES_IN_ZIP} files.")
        chat = ""
        for i in infos:
            name = i.filename.replace("\\", "/")
            if name.lower().endswith(".txt") and "chat" in name.lower() and i.file_size < 20 * 1024 * 1024:
                chat = zf.read(i).decode("utf-8", "ignore")
                break
        senders = _chat_senders(chat) if chat else {}
        images: List[Dict[str, object]] = []
        total = over = skipped = too_big = 0
        for i in infos:
            name = i.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                skipped += 1
                continue
            if i.file_size > MAX_IMAGE_BYTES:
                too_big += 1
                continue
            with zf.open(i) as fh:
                if not _is_image(fh.read(8)):
                    skipped += 1
                    continue
            if len(images) >= max_images:
                over += 1
                continue
            if total + i.file_size > MAX_TOTAL_IMAGE_BYTES:
                warnings.append("Stopped early: the pictures together are too large.")
                break
            blob = zf.read(i)
            total += len(blob)
            base = name.split("/")[-1]
            images.append({"filename": base, "bytes": blob, **senders.get(base, {})})
    if over:
        warnings.append(f"Only the first {max_images} pictures were used; {over} more were skipped "
                        "(send them in another batch).")
    if skipped:
        warnings.append(f"{skipped} file(s) were ignored (videos, voice notes, text, or not a real picture).")
    if too_big:
        warnings.append(f"{too_big} picture(s) were larger than 10 MB and were skipped.")
    return images, warnings