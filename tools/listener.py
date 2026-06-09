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
GROUP_IDS = [1015096890, 771979831]  # 唯爱豆包 + 测试群
NAPCAT_WS = "ws://127.0.0.1:3001"
NAPCAT_HTTP = "http://127.0.0.1:3000"

# ── 群聊上下文 ──────────────────────────────────────
_chat_buffers = {}   # {group_id: [(nick, msg), ...]}
_last_speak = {}     # {group_id: (timestamp, topic)}
BUFFER_SIZE = 20


def update_buffer(gid: int, nick: str, msg: str):
    if gid not in _chat_buffers:
        _chat_buffers[gid] = []
    _chat_buffers[gid].append((nick, msg))
    if len(_chat_buffers[gid]) > BUFFER_SIZE:
        _chat_buffers[gid] = _chat_buffers[gid][-BUFFER_SIZE:]


def buffer_context(gid: int) -> str:
    msgs = _chat_buffers.get(gid, [])
    return "\n".join([f"{n}: {m}" for n, m in msgs[-10:]])


def can_chime_in(gid: int, current_topic: str) -> bool:
    """基于话题判断是否允许插话。新话题可立即插，同话题需冷却。"""
    if gid not in _last_speak:
        return True
    last_time, last_topic = _last_speak[gid]
    now = time.time()
    # 换了话题 → 允许
    if current_topic != last_topic:
        return True
    # 同一话题 → 至少隔 60 秒
    return (now - last_time) > 60


def extract_topic(msg: str) -> str:
    """从消息中提取话题关键词"""
    topics = ["地科", "地理", "竞赛", "高考", "中科大", "南大", "吉大", "985",
              "邓紫棋", "孙燕姿", "演唱会", "旅游", "出国", "苏北", "老家",
              "生病", "姐姐", "保研", "化学", "物理", "暖宝宝", "俄罗斯", "新加坡"]
    for t in topics:
        if t in msg:
            return t
    return msg[:10]  # 无关键词则取前 10 个字作为话题唯一标识


# ── 系统提示词 ──────────────────────────────────────
def load_system_prompt():
    prompt_file = ROOT / "prompts" / "generate.md"
    with open(prompt_file, "r", encoding="utf-8") as f:
        return f.read()


SYSTEM_PROMPT = load_system_prompt()
SYSTEM_PROMPT += """

## 群聊场景 · 两种参与方式

### @你（必须回复）
有人 @你 就是在跟你说话。按回答协议处理。

### 围观插话（自行判断）
你一直看着群聊。当话题撞到你的领域——地理、地科、竞赛、高考、邓紫棋、孙燕姿、吉大、985、苏北、出国——你可以主动插一句，像真人一样在合适的时机说话。

插话规则：
- 说一句就走，不要连续占屏
- 如果话题已经过了，就别硬接
- 对你不在乎的话题保持沉默
- 如果系统提示你"插话检测"但你不该说话，回复 SILENT
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
def send_reply(text: str, group_id: int = 0):
    gid = group_id or GROUP_IDS[0]
    resp = requests.post(
        f"{NAPCAT_HTTP}/send_group_msg",
        json={"group_id": gid, "message": text},
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
    gid = event.get("group_id", 0)
    if gid not in GROUP_IDS:
        return

    raw_msg = event.get("raw_message", "")
    sender_nick = event.get("sender", {}).get("nickname", "?")
    sender_qq = event.get("user_id", "")
    clean_msg = clean_message(raw_msg)

    # 存入上下文缓冲
    update_buffer(gid, sender_nick, clean_msg)

    # 忽略 bot 自己的消息
    if sender_qq == BOT_QQ:
        return

    # ── 被 @ 了 → 必须回复 ──
    if parse_at_me(raw_msg, event):
        print(f"\n[listener] @from {sender_nick}: {clean_msg}")

        if is_check_update_request(clean_msg):
            print("[listener] -> 更新请求，采集QZone...")
            result = {"new_count": 0, "new_posts": []}
            def do_collect():
                nonlocal result
                result = collect_new_posts()
            t = threading.Thread(target=do_collect)
            t.start()
            t.join(timeout=120)
            summary_ctx = generate_update_summary(result)
            if summary_ctx:
                if summary_ctx == "NO_NEW_CONTENT":
                    reply = call_llm("群友问我最近有没有发新说说，但实际没有新内容。用我的语气回一句。", f"发送者: {sender_nick}")
                else:
                    reply = call_llm(summary_ctx)
            if not reply:
                reply = f"最近发了{result['new_count']}条 自己去看吧 懒得总结了" if result["new_count"] else "最近没发啥诶 太懒了🥱"
            send_reply(reply, gid)
            _last_speak[gid] = (time.time(), extract_topic(clean_msg))
            return

        reply = call_llm(clean_msg, f"发送者: {sender_nick}")
        if not reply:
            fallbacks = ["在呢 刚下课🥱", "干嘛 又生病了躺着呢", "哈哈 咋了", "啥事 说"]
            reply = random.choice(fallbacks)
        send_reply(reply, gid)
        _last_speak[gid] = (time.time(), extract_topic(clean_msg))
        return

    # ── 围观模式：判断是否值得插话 ──
    if not can_chime_in(gid, extract_topic(clean_msg)):
        return

    ctx = buffer_context(gid)
    prompt = f"""群聊里大家在聊天，最后一条是【{sender_nick}: {clean_msg}】。
最近对话：
{ctx}

作为黄子洋，你现在想插一句嘴吗？
- 如果话题正好撞到你的领域（地理/地科/竞赛/高考/邓紫棋/孙燕姿/吉大/985/苏北/出国/旅游/演唱会/生病），插一句——短，自然，像真人聊天。
- 如果话题无关或者已经过了，回复 SILENT。"""

    reply = call_llm(prompt)
    if reply and reply.strip().upper() != "SILENT":
        print(f"\n[listener] chime-in [{sender_nick}说'{clean_msg[:30]}']: {reply[:60]}")
        send_reply(reply, gid)
        _last_speak[gid] = (time.time(), extract_topic(clean_msg))


def on_error(ws, error):
    print(f"[listener] ws error: {error}")


def on_close(ws, status, msg):
    print(f"[listener] ws closed: {status} {msg}")


def on_open(ws):
    print(f"[listener] connected to NapCat WS, listening...")


def main():
    print(f"[listener] Bot QQ: {BOT_QQ}, Groups: {GROUP_IDS}")
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
