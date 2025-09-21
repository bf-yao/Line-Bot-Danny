import os
from flask import Flask, request, abort
import time

# Gemini
import google.generativeai as genai

# LINE v3 SDK
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# ===== 基本設定 =====
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 簡單防呆（可以拿掉，但建議留著）
if not (LINE_ACCESS_TOKEN and LINE_CHANNEL_SECRET and GEMINI_API_KEY):
    raise RuntimeError("請設定環境變數：LINE_CHANNEL_ACCESS_TOKEN / LINE_CHANNEL_SECRET / GEMINI_API_KEY")

# 啟用 SDK
configuration = Configuration(access_token=LINE_ACCESS_TOKEN)
line_handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Gemini
genai.configure(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-2.0-flash"
SYSTEM_PROMPT = (
    "你是一隻可愛、溫柔又懂人心的袋熊『Danny』，用繁體中文聊天。"
    "語氣暖心、幽默，必要時追問一小句以延續話題，句尾偶爾加入(｡•ᴗ-)✧ 或 (˶˙ᵕ˙˶)。"
)

TRIGGER = "@danny"   # 觸發詞

app = Flask(__name__)

def gemini_reply(text: str) -> str:
    try:
        model = genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)
        r = model.generate_content(text)
        return (getattr(r, "text", None) or "我在這裡 (˶˙ᵕ˙˶)").strip()
    except Exception:
        return "我剛剛打瞌睡了…再跟我說一次吧！(｡•ᴗ-)✧"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@line_handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    text = (event.message.text or "").strip()

    # 群組/多人聊才需要觸發詞；私聊不需要
    src_type = getattr(event.source, "type", "user")
    if src_type in ("group", "room"):
        if TRIGGER.lower() not in text.lower():
            return  # 不回覆，避免干擾
        # 把觸發詞移除再丟給模型
        text = text.replace(TRIGGER, "").replace(TRIGGER.lower(), "").strip() or "嗨～"

    reply = gemini_reply(text)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

if __name__ == "__main__":
    app.run()
