const TIMEOUT_MS = 5000;

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("OK", { status: 200 });
    }

    const body = await request.text();

    const forwarded = await forwardToLocal(env.LOCAL_URL, body, env.FORWARD_SECRET);
    if (forwarded) {
      return new Response("OK", { status: 200 });
    }

    await notifyOffline(body, env.BOT_TOKEN);
    return new Response("OK", { status: 200 });
  },
};

async function forwardToLocal(localUrl, body, secret) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${localUrl}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Bot-Api-Secret-Token": secret,
      },
      body,
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function notifyOffline(body, botToken) {
  let chatId;
  try {
    const update = JSON.parse(body);
    chatId =
      update?.message?.chat?.id ??
      update?.edited_message?.chat?.id ??
      update?.callback_query?.message?.chat?.id;
  } catch {
    return;
  }
  if (!chatId) return;

  await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text: "⚠️ The bot is currently offline. Please try again later.",
    }),
  }).catch(() => {});
}
