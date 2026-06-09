"""
QQ 群消息监听 + 自动回复。

连接 NapCat WebSocket，监听群消息中 @bot 的事件，
以黄子洋人格自动回复。支持手动模式和 LLM 模式。
"""
import json
import re
import sys
import time
import requests
import websocket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 配置 ─────────────────────────────────────────────
BOT_QQ = 3941207947
GROUP_ID = 1015096890
NAPCAT_WS = "ws://127.0.0.1:3001"
NAPCAT_HTTP = "http://127.0.0.1:3000"

# 系统提示词（从 generate.md 加载）
def load_system_prompt():
    prompt_file = ROOT / "prompts" / "generate.md"
    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read()
    # 提取角色设定和风格约束部分
    return content


SYSTEM_PROMPT = load_system_prompt()

# 追加群聊回复指导
SYSTEM_PROMPT += """
## 群聊回复规则

你现在在 QQ 群"唯爱豆包"里和大家聊天。群友 @你 就是在跟你说话。
- 用短说说风格回复（1-3句话，口语化，自嘲+卖惨）
- 被认真提问时才用长文风格
- 可以调侃自己，但不要自怨自艾超过两句
- 你有自己的事情要做（上课、实验、出去玩），不一定秒回
- 感觉无聊时可以忽略，不要尬聊
"""


# ── LLM 配置（从 config.yaml 读取）─────────────────────
def load_llm_config():
    import yaml
    cfg_file = ROOT / "config.yaml"
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            llm = cfg.get("llm", {})
            return {
                "api_key": llm.get("api_key", ""),
                "api_base": llm.get("api_base", "https://api.deepseek.com/v1"),
                "model": llm.get("model", "deepseek-v4-pro"),
            }
    return {}


LLM_CONFIG = load_llm_config()


# ── LLM 调用 ──────────────────────────────────────────
def call_llm(user_message: str, context: str = "") -> str:
    """调用 LLM 生成回复"""
    api_key = LLM_CONFIG.get("api_key", "")
    api_base = LLM_CONFIG.get("api_base", "https://api.deepseek.com/v1")
    model = LLM_CONFIG.get("model", "dpsk-v4-pro")

    if not api_key:
        return None

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    if context:
        messages.append({"role": "user", "content": f"【群聊上下文】\n{context}"})
    messages.append({"role": "user", "content": user_message})

    try:
        resp = requests.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "max_tokens": 200, "temperature": 0.8},
            timeout=15,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[listener] LLM error: {e}")
        return None


# ── 回复发送 ──────────────────────────────────────────
def send_reply(text: str):
    """通过 NapCat HTTP API 发送群消息"""
    resp = requests.post(
        f"{NAPCAT_HTTP}/send_group_msg",
        json={"group_id": GROUP_ID, "message": text},
        timeout=10,
    )
    if resp.json().get("retcode") == 0:
        print(f"[listener] replied: {text[:60]}...")
    else:
        print(f"[listener] send failed: {resp.text[:100]}")


# ── 消息解析 ──────────────────────────────────────────
def parse_at_me(raw_message: str, event: dict) -> bool:
    """检查消息是否 @了 bot（兼容 CQ 码和纯文本 @）"""
    # 方式1: CQ 码 at
    patterns = [f"[CQ:at,qq={BOT_QQ}]", f"[CQ:at,qq={BOT_QQ}"]
    if any(p in raw_message for p in patterns):
        return True
    # 方式2: 纯文本 @昵称
    nicknames = ["Sakuearil", "hzy", "黄子洋"]
    for nick in nicknames:
        if f"@{nick}" in raw_message:
            return True
    return False


def clean_message(raw_message: str) -> str:
    """去掉 CQ 码，提取纯文本"""
    text = re.sub(r'\[CQ:[^\]]+\]', '', raw_message)
    return text.strip()


# ── 主循环 ────────────────────────────────────────────
def on_message(ws, raw):
    """WebSocket 消息回调"""
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return

    post_type = event.get("post_type")
    if post_type != "message":
        return
    if event.get("message_type") != "group":
        return
    if event.get("group_id") != GROUP_ID:
        return

    raw_msg = event.get("raw_message", "")
    if not parse_at_me(raw_msg, event):
        return

    sender_nick = event.get("sender", {}).get("nickname", "未知")
    clean_msg = clean_message(raw_msg)
    sender_qq = event.get("user_id", "")

    print(f"\n[listener] @from {sender_nick}({sender_qq}): {clean_msg}")

    # 获取群聊上下文（前几条消息）
    context = f"发送者: {sender_nick}\n消息: {clean_msg}"

    # 尝试 LLM 自动回复
    reply = call_llm(clean_msg, context)
    if reply:
        send_reply(reply)
    else:
        # 无 LLM 时用预设回复（不阻塞）
        fallbacks = [
            "在呢，刚下课🥱",
            "干嘛，又生病了躺着呢",
            "哈哈",
            "忙着呢 在看地理的东西",
            "啥事",
            "刚睡醒 这体质真是没谁了",
            "在想今天吃啥",
        ]
        import random
        send_reply(random.choice(fallbacks))


def on_error(ws, error):
    print(f"[listener] ws error: {error}")


def on_close(ws, status, msg):
    print(f"[listener] ws closed: {status} {msg}")


def on_open(ws):
    print(f"[listener] connected to NapCat WS, listening...")


def main():
    print(f"[listener] Bot QQ: {BOT_QQ}, Group: {GROUP_ID}")
    print(f"[listener] connecting to {NAPCAT_WS}...")

    ws = websocket.WebSocketApp(
        NAPCAT_WS,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    ws.run_forever()


if __name__ == "__main__":
    main()
