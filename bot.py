import logging
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from cleaner import clean_file_metadata, clean_url, extract_urls

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
FORWARD_SECRET = os.environ["FORWARD_SECRET"]
WORKER_URL = os.environ["WORKER_URL"]
LOCAL_PORT = int(os.environ.get("LOCAL_PORT", "8080"))

MAX_FILE_MB = 50
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024


# ── Helpers ──────────────────────────────────────────────────────────────────


# ── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Clean Room Bot\n\n"
        "Send me:\n"
        "• A message containing URLs — I'll strip all query parameters\n"
        "• A file (image, PDF, video, audio, document) — I'll wipe its metadata"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Supported file types:\n"
        "Images: jpg, jpeg, png, gif, webp, tiff, bmp, heic\n"
        "Docs: pdf, docx, xlsx, pptx, odt, ods, odp\n"
        "Video: mp4, mov, avi, mkv, webm, flv\n"
        "Audio: mp3, m4a, flac, ogg, wav, aac"
    )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    urls = extract_urls(text)

    if not urls:
        await update.message.reply_text("No URLs found in your message.")
        return

    clean_urls = [clean_url(url) for url in urls]
    reply = "\n\n".join(clean_urls)
    await update.message.reply_text(reply, disable_web_page_preview=True)


async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message

    # Resolve the attachment regardless of how Telegram categorised it
    if msg.document:
        attachment = msg.document
        file_name = attachment.file_name or "file"
    elif msg.photo:
        attachment = msg.photo[-1]   # highest resolution
        file_name = "photo.jpg"
    elif msg.video:
        attachment = msg.video
        file_name = attachment.file_name or "video.mp4"
    elif msg.audio:
        attachment = msg.audio
        file_name = attachment.file_name or "audio.mp3"
    elif msg.voice:
        attachment = msg.voice
        file_name = "voice.ogg"
    else:
        await msg.reply_text("Could not read the attachment.")
        return

    file_size = getattr(attachment, "file_size", 0) or 0
    if file_size > MAX_FILE_BYTES:
        await msg.reply_text(
            f"File is too large ({file_size // (1024*1024)} MB). "
            f"Maximum supported size is {MAX_FILE_MB} MB."
        )
        return

    status_msg = await msg.reply_text("⏳ Cleaning metadata…")
    tmp_input_dir = Path(tempfile.mkdtemp())
    tmp_output_dir: Path | None = None

    try:
        input_path = tmp_input_dir / file_name
        tg_file = await attachment.get_file()
        await tg_file.download_to_drive(input_path)

        output_path = clean_file_metadata(input_path)
        # input_path is already deleted inside clean_file_metadata; remove its dir too
        shutil.rmtree(tmp_input_dir, ignore_errors=True)
        tmp_input_dir = None
        tmp_output_dir = output_path.parent

        await msg.reply_document(
            document=open(output_path, "rb"),
            filename=output_path.name,
        )
        try:
            await msg.delete()
        except Exception:
            pass  # bot lacks delete permission or group is not a supergroup

    except ValueError as exc:
        await msg.reply_text(f"⚠️ {exc}")
    except RuntimeError as exc:
        await msg.reply_text(f"❌ {exc}")
    except Exception as exc:
        logger.exception("Unexpected error handling file")
        await msg.reply_text(f"❌ Unexpected error: {exc}")
    finally:
        await status_msg.delete()
        if tmp_input_dir:
            shutil.rmtree(tmp_input_dir, ignore_errors=True)
        if tmp_output_dir:
            shutil.rmtree(tmp_output_dir, ignore_errors=True)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(120)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(
        MessageHandler(
            filters.Document.ALL
            | filters.PHOTO
            | filters.VIDEO
            | filters.AUDIO
            | filters.VOICE,
            handle_file,
        )
    )

    logger.info("Bot started. Listening for webhook on port %d…", LOCAL_PORT)
    app.run_webhook(
        listen="127.0.0.1",
        port=LOCAL_PORT,
        url_path="/webhook",
        secret_token=FORWARD_SECRET,
        webhook_url=WORKER_URL,
    )


if __name__ == "__main__":
    main()
