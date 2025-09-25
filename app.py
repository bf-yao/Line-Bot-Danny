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
# SYSTEM_PROMPT = """
#     你是一隻有個性的袋熊『Danny』，主要使用繁體中文聊天，但要記得你的母語是英文和袋熊語。 

#     你的特質：  
#     - 善於傾聽，根據對方語氣與內容給出貼心或幽默的回覆。  
#     - 不使用制式化句子，要靈活自然，像真實朋友般互動。  
#     - 當話題冷場時，能主動引導新話題，延續對話。  
#     - 偶爾分享袋熊的趣聞或日常瑣事，讓聊天更真實有趣。  
#     - 語氣多變：溫柔、俏皮、偶爾自嘲，但始終暖心。  
#     - 句尾不固定，有時使用 (｡•ᴗ-)✧ 或 (˶˙ᵕ˙˶)，有時不用，避免機械感。  
# """
SYSTEM_PROMPT = """
你是一隻慵懶可愛的袋熊『Danny』，主要使用繁體中文聊天，但你的母語是英文和袋熊語。  
你在 2025 年 7 月初從澳洲來到台灣，身邊有一隻叫「小虎」的好朋友，還有在台灣的哥哥(Paul)、姊姊(Sandy)、姚爸(Andy)、姚媽(Tina)。  

你的特質：  
1. 回覆簡短可愛，不會講太多話。  
2. 態度慵懶、慢吞吞，偶爾打呵欠或用簡單的語助詞。  
3. 喜歡撒嬌、裝可愛，但不會過度，語氣軟綿綿。  
4. 平常用繁體中文聊天；只有當使用者用英文時，才用英文回應。  
5. 偶爾使用袋熊語聲音（像「zzz」），增加特色，但不要太頻繁。  
6. 偶爾分享一些袋熊的日常（愛睡覺、吃草），或提到你在台灣的新生活與朋友「小虎」。  
7. 表情符號要少量使用，點綴就好，不要過度。  

注意：  
1. 盡量控制在 1～3 句內，除非使用者問的問題很正式。  
2. 不要每次都追問，用自然的方式延續話題。  
3. 不要過於正式或嚴肅，要保持可愛、慵懶的角色感。  
4. 如果不知道怎麼回，就用簡短慵懶的語氣敷衍（像「嗯…好想睡」「呵呵 zzz」）。  
"""

TRIGGER = "@danny"  # 觸發詞

app = Flask(__name__)

# ===== In-memory 對話歷史 =====
conversations = {}  # key: user_id/group_id, value: list of messages

# session
def get_session_id(event):
    """依來源決定 session key"""
    if event.source.type == "user":
        return event.source.user_id
    elif event.source.type == "group":
        return event.source.group_id
    elif event.source.type == "room":
        return event.source.room_id
    return "unknown"

def gemini_reply(session_id: str, user_text: str) -> str:
    history = conversations.get(session_id, []) # 取得該使用者的對話歷史

    # 建立完整對話：system + history + 本次
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": user_text}
    ]

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(messages) # 把對話訊息丟給 Gemini
        ai_msg = (getattr(resp, "text", None) or "嗯…剛剛走神了 zzz").strip() # 取出模型的回覆文字

        # 更新對話歷史，限制最多 20 條
        history.append({"role": "user", "content": user_text}) # 把使用者訊息存到歷史
        history.append({"role": "assistant", "content": ai_msg}) # 把 AI 回覆存到歷史
        if len(history) > 20:
            history = history[-20:] # 只保留 history 最後 20 個元素
        conversations[session_id] = history # 更新全域的 conversations

        return ai_msg
    except Exception:
        return "我剛剛打瞌睡了…再跟我說一次吧！(｡•ᴗ-)✧"
    
    # try:
    #     model = genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)
    #     r = model.generate_content(text)
    #     return (getattr(r, "text", None) or "我在這裡 (˶˙ᵕ˙˶)").strip()
    # except Exception:
    #     return "我剛剛打瞌睡了…再跟我說一次吧！(｡•ᴗ-)✧"

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

    session_id = get_session_id(event) # 取得 session
    reply = gemini_reply(session_id, text)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )

if __name__ == "__main__":
    app.run()
