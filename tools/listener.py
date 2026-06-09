"""
QQ 群消息监听 + 自动回复 + 动态检查。

- 被 @ 时以黄子洋人格回复
- 被问到"有更新吗/发说说没"时，自动采集 QZone 新内容并回复
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import random

import requests
import websocket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 配置 ─────────────────────────────────────────────
BOT_QQ = 3941207947
GROUP_ID = 1015096890
NAPCAT_WS = "ws://127.0.0.1:3001"
NAPCAT_HTTP = "http://127.0.0.1:3000"


def load_system_prompt():
    prompt_file = ROOT / "prompts" / "generate.md"
    with open(prompt_file, "r", encoding="utf-8") as f:
        return f.read()


SYSTEM_PROMPT = load_system_prompt()
SYSTEM_PROMPT += """
## 群聊回复规则

你现在在 QQ 群"唯爱豆包"里和大家聊天。群友 @你 就是在跟你说话。
- 用短说说风格回复（1-3句话，口语化）
- 被认真提问时才用长文风格
- 可以调侃自己，但不要自怨自艾超过两句

## 动态更新回复规则（重要）

如果群友问你"有新说说吗""最近发没发动态""空间更新了没"之类的问题：
1. 立即回复"我去看看..."之类的话，表示你正在检查
2. 系统会自动拉取最新说说，然后告诉你结果
3. 如果系统告诉你没有新内容，就回复"最近没发什么诶"之类
4. 如果系统告诉你有新内容，就简短总结（1-2句）聊一下最近发了什么
"""


# ── LLM 配置 ──────────────────────────────────────────
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
    api_key = LLM_CONFIG.get("api_key", "")
    api_base = LLM_CONFIG.get("api_base", "https://api.deepseek.com/v1")
    model = LLM_CONFIG.get("model", "deepseek-v4-pro")
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
            json={"model": model, "messages": messages,
                  "max_tokens": 300, "temperature": 0.8},
            timeout=20,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[listener] LLM error: {e}")
        return None


# ── 回复发送 ──────────────────────────────────────────
def send_reply(text: str):
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
    patterns = [f"[CQ:at,qq={BOT_QQ}]", f"[CQ:at,qq={BOT_QQ}"]
    if any(p in raw_message for p in patterns):
        return True
    nicknames = ["Sakuearil", "hzy", "黄子洋"]
    for nick in nicknames:
        if f"@{nick}" in raw_message:
            return True
    return False


def clean_message(raw_message: str) -> str:
    text = re.sub(r'\[CQ:[^\]]+\]', '', raw_message)
    return text.strip()


def is_check_update_request(msg: str) -> bool:
    """判断是否在问动态更新"""
    patterns = [
        r'(?:有|发|更)(?:新|了|过)?(?:\s*(?:说说|空间|动态|QZone|qq空间))',
        r'(?:说说|空间|动态)(?:\s*(?:有|发|更)(?:新|了|过)?)',
        r'(?:最近|最近有|有没有)(?:发|更)(?:说说|动态|空间)',
        r'(?:看看|瞅瞅|查一下)(?:说说|空间|动态)',
        r'(?:抓|拉|获取|同步)(?:一下|下)?(?:说说|动态)',
        r'(?:有新)?(?:内容|东西)(?:吗|没|了)',
    ]
    for p in patterns:
        if re.search(p, msg):
            return True
    return False


# ── 动态采集与对比 ────────────────────────────────────
def collect_new_posts() -> dict:
    """
    采集 QZone 最新说说，对比已有语料，返回新内容。
    在子线程中运行，不阻塞 WebSocket。
    """
    print("[listener] 开始采集 QZone 新说说...")

    # 记录采集前的文件列表（用于去重）
    raw_file = ROOT / "raw" / "qzone_1318846394.json"
    old_ids = set()
    if raw_file.exists():
        with open(raw_file, "r", encoding="utf-8") as f:
            try:
                old_data = json.load(f)
                old_ids = {d.get("platform_id", "") for d in old_data}
            except:
                pass

    # 运行采集脚本
    collector = ROOT / "tools" / "collect_qzone.py"
    try:
        result = subprocess.run(
            [sys.executable, str(collector), "1318846394", "3"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(f"[listener] collector exit: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("[listener] collector timeout")
        return {"new_count": 0, "new_posts": [], "error": "采集超时"}
    except Exception as e:
        print(f"[listener] collector error: {e}")
        return {"new_count": 0, "new_posts": [], "error": str(e)}

    # 对比新旧
    if not raw_file.exists():
        return {"new_count": 0, "new_posts": []}

    with open(raw_file, "r", encoding="utf-8") as f:
        try:
            new_data = json.load(f)
        except:
            return {"new_count": 0, "new_posts": []}

    new_posts = []
    for d in new_data:
        pid = d.get("platform_id", "")
        if pid and pid not in old_ids:
            new_posts.append(d)

    # 如果有新内容，清洗入库
    if new_posts:
        print(f"[listener] 发现 {len(new_posts)} 条新说说，入库中...")
        # 只保留新内容写回 raw，然后跑 cleaner
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(new_posts, f, ensure_ascii=False, indent=2)
        cleaner = ROOT / "tools" / "clean_qzone.py"
        subprocess.run(
            [sys.executable, str(cleaner)],
            cwd=str(ROOT),
            capture_output=True,
            timeout=60,
        )

    return {
        "new_count": len(new_posts),
        "new_posts": new_posts,
    }


def generate_update_summary(result: dict) -> str:
    """根据采集结果生成回复"""
    new_count = result.get("new_count", 0)
    new_posts = result.get("new_posts", [])

    if result.get("error"):
        return None  # 让 LLM 自由发挥

    if new_count == 0:
        return "NO_NEW_CONTENT"  # 特殊标记，LLM 会处理

    # 有内容时：给 LLM 提供新内容摘要
    summaries = []
    for p in new_posts[:5]:
        content = p.get("content", "")[:80].replace("\n", " ")
        summaries.append(f"- {content}")
    context = f"刚采集到 {new_count} 条新说说:\n" + "\n".join(summaries)
    context += "\n\n用黄子洋的语气简短总结一下最近发了什么（1-2句话）。"
    return context


# ── 主循环 ────────────────────────────────────────────
def on_message(ws, raw):
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return

    if event.get("post_type") != "message":
        return
    if event.get("message_type") != "group":
        return
    if event.get("group_id") != GROUP_ID:
        return

    raw_msg = event.get("raw_message", "")
    if not parse_at_me(raw_msg, event):
        return

    sender_nick = event.get("sender", {}).get("nickname", "?")
    clean_msg = clean_message(raw_msg)
    sender_qq = event.get("user_id", "")

    print(f"\n[listener] @from {sender_nick}({sender_qq}): {clean_msg}")

    # 检查是否在问动态更新
    if is_check_update_request(clean_msg):
        print("[listener] -> 检测到更新请求，采集QZone...")

        result = {"new_count": 0, "new_posts": []}

        def do_collect():
            nonlocal result
            result = collect_new_posts()

        t = threading.Thread(target=do_collect)
        t.start()
        t.join(timeout=120)

        # 用 LLM 生成自然回复
        summary_ctx = generate_update_summary(result)
        if summary_ctx:
            if summary_ctx == "NO_NEW_CONTENT":
                # 让 LLM 自由发挥说没更新
                reply = call_llm("群友问我最近有没有发新说说，但实际没有新内容。用我的语气回一句，简短自然。", f"发送者: {sender_nick}")
            else:
                reply = call_llm(summary_ctx)

        if not reply:
            # 兜底：黄子洋口吻
            if result["new_count"] == 0:
                reply = "最近没发啥诶 太懒了🥱"
            else:
                reply = f"刚看了一下 最近发了{result['new_count']}条 自己去看吧 懒得总结了哈哈"
        send_reply(reply)
        return

    # 普通 @ 回复
    context = f"发送者: {sender_nick}\n消息: {clean_msg}"
    reply = call_llm(clean_msg, context)
    if not reply:
        # 兜底：黄子洋口吻
        fallbacks = [
            "在呢 刚下课🥱",
            "干嘛 又生病了躺着呢",
            "哈哈 咋了",
            "忙着呢 在看地理的东西",
            "啥事 说",
            "刚睡醒 这体质真是没谁了",
            "在想今天吃啥 饿了",
        ]
        reply = random.choice(fallbacks)
    send_reply(reply)


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
