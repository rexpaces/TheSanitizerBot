import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    # UTM
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    # Google
    "gclid", "gclsrc", "gbraid", "wbraid", "dclid",
    "_ga", "_gl",
    # Facebook / Meta
    "fbclid", "fb_action_ids", "fb_action_types", "fb_ref", "fb_source",
    # Microsoft / Bing
    "msclkid",
    # Twitter / X
    "twclid",
    # LinkedIn
    "li_fat_id",
    # Mailchimp
    "mc_cid", "mc_eid",
    # Instagram
    "igshid",
    # Yandex
    "yclid",
    # HubSpot
    "_hsenc", "_hsmi", "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad",
    "hsa_src", "hsa_tgt", "hsa_kw", "hsa_mt", "hsa_net", "hsa_ver",
    # Marketo
    "mkt_tok",
    # Adobe
    "ef_id", "s_kwcid",
    # Other common ones
    "ref", "referrer", "source", "zanpid", "origin",
}

SUPPORTED_EXTENSIONS = {
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp", ".heic",
    # Documents
    ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
    # Video
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv",
    # Audio
    ".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac",
}

URL_PATTERN = re.compile(r'(?:https?://|www\.)\S+|(?<!\w)[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:[/?\S]*)?')


def extract_urls(text: str) -> list[str]:
    return URL_PATTERN.findall(text)


def clean_url(url: str) -> str:
    """Remove scheme, all query parameters and fragments from a URL."""
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    clean = urlunparse(parsed._replace(scheme="", query="", fragment=""))
    return re.sub(r'^www\.', '', clean.lstrip("://"))


def clean_file_metadata(input_path: Path) -> tuple[Path, dict]:
    """
    Strip all metadata from a file using exiftool.
    Returns (output_path_in_tempdir, info_dict).
    Caller is responsible for cleaning up the temp directory.
    """
    if not shutil.which("exiftool"):
        raise RuntimeError(
            "exiftool is not installed. Install it with:\n"
            "  macOS:  brew install exiftool\n"
            "  Debian: sudo apt install libimage-exiftool-perl"
        )

    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: `{suffix}`")

    tmp_dir = Path(tempfile.mkdtemp())
    random_name = secrets.token_hex(16) + input_path.suffix.lower()
    output_path = tmp_dir / random_name
    shutil.copy2(input_path, output_path)

    # Delete the original as soon as the copy is made
    input_path.unlink(missing_ok=True)

    # Strip all metadata
    strip_result = subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", str(output_path)],
        capture_output=True, text=True
    )

    if strip_result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"exiftool error: {strip_result.stderr.strip()}")

    return output_path
