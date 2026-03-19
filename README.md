# Clean Room Bot

A Telegram bot that removes tracking data from things you share:

- **URLs** — strips all tracking query parameters (UTM, fbclid, gclid, and dozens more)
- **Files** — wipes embedded metadata (EXIF, document properties, etc.) from images, PDFs, Office documents, videos, and audio files

Supported file types: `jpg jpeg png gif webp tiff bmp heic pdf docx xlsx pptx odt ods odp mp4 mov avi mkv webm flv mp3 m4a flac ogg wav aac`

---

## Architecture

The bot runs on a **local machine** (your own computer or home server). Since Telegram requires a public HTTPS endpoint to deliver messages, the setup uses two free Cloudflare services to bridge the gap:

```
Telegram
   │
   │  webhook POST (HTTPS)
   ▼
Cloudflare Worker          ← always online, forwards updates
   │
   │  forwards to tunnel (5s timeout)
   ▼
Cloudflare Tunnel          ← exposes local machine to the internet
   │
   ▼
Local bot (localhost:8080) ← does the actual work
```

If the local bot is offline (machine is off, bot crashed, etc.), the Worker detects the failed forward and sends the user a "bot is currently offline" message via the Telegram API directly — so users are never left waiting with no response.

### Components

| File | Role |
|---|---|
| `bot.py` | The Telegram bot. Listens for webhook POSTs on `localhost:8080`. |
| `cleaner.py` | URL cleaning and file metadata stripping logic (uses `exiftool`). |
| `worker.js` | Cloudflare Worker. Receives Telegram webhooks and forwards to the local bot. |
| `wrangler.toml` | Cloudflare Worker deployment config. |

---

## Prerequisites

- Python 3.11+
- Node.js (for Wrangler CLI)
- `exiftool` installed on the local machine
- A Cloudflare account (free)
- A domain managed by Cloudflare (needed for the tunnel public hostname)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Install exiftool

```bash
# macOS
brew install exiftool

# Debian/Ubuntu
sudo apt install libimage-exiftool-perl
```

---

## Setup

### 1. Clone and install Python dependencies

```bash
git clone <repo-url>
cd clean-room
pip install -r requirements.txt
```

### 2. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the token BotFather gives you (format: `123456789:AAB...`)

### 3. Set up the Cloudflare Tunnel

The tunnel gives your local machine a stable public HTTPS URL without opening ports or having a static IP.

#### 3a. Install cloudflared

```bash
# macOS
brew install cloudflare/cloudflare/cloudflared

# Debian/Ubuntu
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb
```

#### 3b. Authenticate

```bash
cloudflared tunnel login
```

This opens a browser. Log in with your Cloudflare account and authorize the domain you want to use.

#### 3c. Create a named tunnel

```bash
cloudflared tunnel create my-local-services
```

This prints a **Tunnel ID** (UUID). Keep it — you need it in the next step.

#### 3d. Create the tunnel config file

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <your-tunnel-id>
credentials-file: /Users/<you>/.cloudflared/<your-tunnel-id>.json

ingress:
  - hostname: cleanroom.yourdomain.com
    service: http://localhost:8080
  - service: http_status:404
```

Replace `<your-tunnel-id>` and `yourdomain.com` with your values.

#### 3e. Add your domain to Cloudflare (if not already)

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) → **Add a domain**
2. Enter your domain and follow the steps
3. Cloudflare will give you two nameservers — update them at your domain registrar
4. Wait for Cloudflare to confirm the domain is active (usually 5–30 minutes)

#### 3f. Create the DNS record for the tunnel

```bash
cloudflared tunnel route dns my-local-services cleanroom.yourdomain.com
```

#### 3g. Start the tunnel

```bash
cloudflared tunnel run my-local-services
```

You should see `Connection established` in the output. Your bot will be reachable at `https://cleanroom.yourdomain.com`.

### 4. Deploy the Cloudflare Worker

The Worker is the always-online layer that receives Telegram webhooks and forwards them to your local bot.

#### 4a. Install Wrangler

```bash
npm install -g wrangler
wrangler login
```

#### 4b. Deploy the Worker

```bash
wrangler deploy --name clean-room-bot-proxy
```

After deploy, Wrangler prints your Worker URL:
```
https://clean-room-bot-proxy.<your-subdomain>.workers.dev
```

#### 4c. Set Worker secrets

```bash
wrangler secret put BOT_TOKEN --name clean-room-bot-proxy
# enter your Telegram bot token

wrangler secret put LOCAL_URL --name clean-room-bot-proxy
# enter: https://cleanroom.yourdomain.com

wrangler secret put FORWARD_SECRET --name clean-room-bot-proxy
# enter: any long random string (e.g. output of: openssl rand -hex 32)
```

`FORWARD_SECRET` is a shared secret between the Worker and the local bot. The Worker sends it as a header with every forwarded request; the bot rejects requests that don't include it.

### 5. Configure the local bot

Create a `.env` file in the project root:

```env
BOT_TOKEN=<your-telegram-bot-token>
FORWARD_SECRET=<same-random-string-as-worker-secret>
WORKER_URL=https://clean-room-bot-proxy.<your-subdomain>.workers.dev
LOCAL_PORT=8080
```

### 6. Run the bot

```bash
python bot.py
```

On startup the bot registers the Telegram webhook to point at the Cloudflare Worker automatically. You should see:

```
Bot started. Listening for webhook on port 8080…
```

Send `/start` to your bot on Telegram to verify everything works.

---

## Running order

Every time you start the system, start things in this order:

1. **Cloudflare Tunnel** — `cloudflared tunnel run my-local-services`
2. **Bot** — `python bot.py`

The Worker is always running on Cloudflare — you never need to restart it unless you redeploy.

---

## Environment variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from BotFather |
| `FORWARD_SECRET` | Shared secret between Worker and bot for request verification |
| `WORKER_URL` | Your Cloudflare Worker URL — used to register the Telegram webhook on startup |
| `LOCAL_PORT` | Port the local bot listens on (default: `8080`) |

---

## How the offline notification works

When your local machine is off or the bot is not running, the Cloudflare Tunnel is also down. When a user sends a message:

1. Telegram delivers the update to the Worker
2. The Worker tries to forward it to `https://cleanroom.yourdomain.com/webhook` with a 5-second timeout
3. The tunnel is unreachable — the request fails immediately
4. The Worker calls the Telegram API directly and sends the user: `⚠️ The bot is currently offline. Please try again later.`
5. The Worker returns `200 OK` to Telegram so it does not retry

---

## Security notes

- The `.env` file is gitignored and must never be committed
- `FORWARD_SECRET` ensures only the Worker can send updates to the local bot — direct requests to the tunnel URL without the secret are rejected by the bot
- Regenerate your bot token via BotFather if it is ever exposed
