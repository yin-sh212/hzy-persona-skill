"""
QQ 群推送器，通过 NapCat HTTP API 发送消息。
"""
import json
import re
import sys
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NAPCAT_URL = "http://127.0.0.1:3000"
GROUP_ID = 1015096890


def push_message(text: str) -> bool:
    """发送纯文本消息到目标 QQ 群"""
    resp = requests.post(
        f"{NAPCAT_URL}/send_group_msg",
        json={"group_id": GROUP_ID, "message": text},
        timeout=10,
    )
    data = resp.json()
    if data.get("retcode") == 0:
        print(f"[pusher] 发送成功, msg_id={data['data']['message_id']}")
        return True
    else:
        print(f"[pusher] 发送失败: {data.get('wording', resp.text)}")
        return False


def load_summary(filepath: str) -> str:
    """从语料库中读取推送总结，转为纯文本"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 去掉 markdown 元数据头
    lines = content.strip().split("\n")
    body_lines = []
    in_body = False
    for line in lines:
        if line.startswith("# date:") or line.startswith("# type:") or line.startswith("# tags:"):
            continue
        if line.startswith("---"):
            break
        if not line.startswith("#") and line.strip():
            in_body = True
        if in_body:
            body_lines.append(line)

    text = "\n".join(body_lines).strip()
    # 去掉 markdown 格式标记
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    return text


def check_and_push(newest_md: str = None):
    """发送最新的推送总结"""
    if newest_md:
        summary_file = Path(newest_md)
    else:
        # 找最近的推送记录
        push_dir = ROOT / "corpus" / "推送记录"
        files = sorted(push_dir.glob("*.md"))
        if not files:
            print("[pusher] 没有找到推送记录")
            return
        summary_file = files[-1]

    if not summary_file.exists():
        print(f"[pusher] 文件不存在: {summary_file}")
        return

    text = load_summary(str(summary_file))
    print(f"[pusher] push {len(text)} chars from {summary_file.name}")
    ok = push_message(text)
    if ok:
        print("[pusher] done")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_and_push(sys.argv[1])
    else:
        check_and_push()
