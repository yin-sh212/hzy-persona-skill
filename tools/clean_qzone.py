"""
清洗 QZone 采集的原始 JSON，去噪后分类入库 corpus。
"""
import json, re, sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
sys.path.insert(0, str(ROOT))

from tools.classifier import classify


def clean_content(raw: str) -> dict:
    """清洗单条说说原始文本，返回结构化数据"""
    text = raw.strip()

    # 1. 去掉昵称前缀
    text = re.sub(r'^烟霭载月~\s*', '', text)

    # 2. 提取日期
    date_match = re.search(
        r'((?:编辑于\s*)?(?:20\d{2}年\d{1,2}月\d{1,2}日))',
        text
    )
    pub_date = ""
    if date_match:
        pub_date = date_match.group(1).replace("编辑于 ", "")
        # 尝试转为 ISO 格式
        try:
            dt = datetime.strptime(pub_date.replace("年", "-").replace("月", "-").replace("日", ""), "%Y-%m-%d")
            pub_date = dt.strftime("%Y-%m-%d")
        except:
            pass

    # 3. 切掉评论区域（从"评论(N)转发更多"开始，或从第一个"XXX :"评论开始）
    # 先标记评论开始位置
    comment_start = re.search(
        r'(?:评论\(\d+\))?转发更多\s',
        text
    )
    if comment_start:
        body = text[:comment_start.start()].strip()
        comments_raw = text[comment_start.end():].strip()
    else:
        # 尝试找 "XXX : " 作为评论开始（但不要误伤正文中的冒号）
        # 评论通常在末尾，格式为 "昵称 : 内容 日期"
        comment_match = re.search(
            r'\s{2,}([^\s:：]+)\s*[：:]\s*.+?\d{4}-\d{1,2}-\d{1,2}',
            text
        )
        if comment_match:
            body = text[:comment_match.start()].strip()
            comments_raw = text[comment_match.start():].strip()
        else:
            body = text
            comments_raw = ""

    # 4. 去掉正文中的元数据尾巴
    body = re.sub(r'查看全部\d+张照片', '', body)
    body = re.sub(r'>\s*>?\s*$', '', body)  # 末尾的 > 符号
    body = re.sub(r'展开查看全文\s*$', '', body)
    body = re.sub(r'\s*来自vivo\s+X100s?\s*Pro\s*(?:\(5G\))?\s*$', '', body)
    body = body.strip()

    # 5. 如果内容里有 "...... 展开查看全文"，说明文本被截断了
    truncated = "展开查看全文" in raw

    return {
        "body": body,
        "date": pub_date,
        "comments_raw": comments_raw,
        "truncated": truncated,
    }


def main():
    input_file = ROOT / "raw" / f"qzone_1318846394.json"
    if not input_file.exists():
        print(f"文件不存在: {input_file}")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    print(f"共 {len(raw_data)} 条待清洗\n")

    saved = 0
    for i, item in enumerate(raw_data):
        raw_text = item.get("content", "")
        cleaned = clean_content(raw_text)
        body = cleaned["body"]
        pub_date = cleaned["date"]

        if not body or len(body) < 5:
            print(f"  [{i+1}] 跳过（空内容）")
            continue

        # 分类
        cat, tags = classify(body)

        # 生成简短标题（取正文前 20 字），去掉不可见字符和非法文件名字符
        title = body.replace('\n', ' ').replace('\r', '')
        title = re.sub(r'[\s#​‌‍﻿]+', '', title)
        title = title.encode('gbk', errors='ignore').decode('gbk')
        # 去掉 Windows 文件名非法字符
        title = re.sub(r'[<>:"/\\|?*~>#]', '', title)
        title = title[:20]

        # 生成文件名
        if pub_date:
            filename = f"{pub_date}_{title}.md"
        else:
            filename = f"unknown_{title}.md"

        filepath = CORPUS / cat / filename

        # 去重
        if filepath.exists():
            print(f"  [{i+1}] 跳过（已存在）: [{cat}] {title}")
            continue

        # 写入
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n")
            f.write(f"# date: {pub_date}\n")
            f.write(f"# tags: {','.join(tags)}\n")
            f.write(f"# source: QQ空间\n")
            if cleaned["truncated"]:
                f.write(f"# truncated: true\n")
            f.write("\n")
            f.write(body)
            if cleaned["comments_raw"]:
                f.write("\n\n---\n## 评论\n")
                f.write(cleaned["comments_raw"])

        saved += 1
        print(f"  [{i+1}] [{cat}] {pub_date} | {title}...")

    print(f"\n完成: 入库 {saved} 篇（跳过 {len(raw_data) - saved} 篇）")


if __name__ == "__main__":
    main()
