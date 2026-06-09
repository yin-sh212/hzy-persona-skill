"""
QQ空间说说采集 - Playwright版。
参考 Ritori2022/qq-space-export 的页面 DOM 抓取思路。
"""
import json, re, sys, time
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def collect(uin: str, max_pages: int = 50):
    with sync_playwright() as p:
        user_data_dir = str(ROOT / ".browser_data")
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        # 1. 打开空间首页，先让用户看到登录状态
        print("[collect] 打开 QZone 首页...")
        page.goto("https://qzone.qq.com/", wait_until="commit", timeout=30000)
        page.wait_for_timeout(3000)

        # 2. 检查登录态
        cookies = context.cookies()
        has_login = any(c["name"] == "p_skey" for c in cookies)
        if not has_login:
            print("[!] 需要登录。请在浏览器窗口中扫码或输入账号密码。")
            print("   等待登录中（每 5 秒检查一次，最多等 120 秒）...")
            for _ in range(24):
                time.sleep(5)
                cookies = context.cookies()
                if any(c["name"] == "p_skey" for c in cookies):
                    has_login = True
                    print("[collect] 登录检测成功")
                    break
            else:
                print("[collect] 登录超时")
                context.close()
                return []

        # 3. 访问目标用户的说说页面
        shuoshuo_url = f"https://user.qzone.qq.com/{uin}/311"
        print(f"[collect] 访问说说页: {shuoshuo_url}")
        page.goto(shuoshuo_url, wait_until="commit", timeout=30000)
        page.wait_for_timeout(5000)

        # 4. 尝试找到 iframe 并切换进入
        all_data = []
        try:
            # QZone 说说内容通常在 #app_container 下的 iframe 中
            iframe = page.wait_for_selector(
                "#app_container iframe, .app_canvas_frame",
                timeout=15000
            )
            frame = iframe.content_frame()
            if frame:
                print("[collect] 进入 iframe")
                page = frame  # 后续操作在 iframe 内
                page.wait_for_timeout(5000)
        except:
            print("[collect] 未找到 iframe，尝试直接在主页面提取")

        # 5. 提取说说
        selectors = [
            "#msgList li.feed",
            "ol.mod_feed_lst li.feed",
            "li.feed",
            ".f-single",
            ".msgcnt",
        ]
        best_sel = None
        for sel in selectors:
            try:
                els = page.locator(sel).all()
                if els:
                    best_sel = sel
                    print(f"[collect] 使用选择器 '{sel}'，找到 {len(els)} 个元素")
                    break
            except:
                continue

        if not best_sel:
            # debug: dump page HTML
            html = page.evaluate("() => document.body.innerHTML.substring(0, 3000)")
            print(f"[collect] 未找到说说元素，页面 HTML: {html}")
            context.close()
            return []

        # 6. 翻页提取
        for page_num in range(max_pages):
            page.wait_for_timeout(2000)
            items = page.locator(best_sel).all()
            print(f"[collect] 第 {page_num+1} 页: {len(items)} 条")

            new_count = 0
            for item in items:
                try:
                    text = item.inner_text().strip()
                    if not text or len(text) < 5:
                        continue
                    # 去重
                    if any(d.get("raw_text") == text for d in all_data):
                        continue
                    # 提取图片
                    imgs = []
                    for img in item.locator("img").all():
                        src = img.get_attribute("src") or ""
                        if "qpic.cn" in src and "qlogo" not in src:
                            imgs.append(src)
                    all_data.append({
                        "content": text,
                        "images": imgs,
                        "raw_text": text,
                    })
                    new_count += 1
                except:
                    continue

            print(f"[collect]   本页新增 {new_count}，累计 {len(all_data)}")

            # 翻页
            next_clicked = False
            for next_text in ["下一页", "下页", "»"]:
                try:
                    btn = page.locator(f"a:text-is('{next_text}')").first
                    if btn.is_visible():
                        btn.click()
                        next_clicked = True
                        break
                except:
                    continue

            if not next_clicked:
                # 尝试滚动到底部触发加载
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(3000)
                # 检查是否有新元素
                new_items = page.locator(best_sel).all()
                if len(new_items) <= len(items):
                    print("[collect] 无更多内容")
                    break

        context.close()
        return all_data


def parse_raw(item: dict) -> dict:
    """清理原始提取的数据"""
    content = item.get("raw_text", "")
    # 基础清洗：去时间、去互动信息
    content = re.sub(r'\d+分钟前|\d+小时前|昨天|今天|前天', '', content)
    content = re.sub(r'\d+个人觉得很赞', '', content)
    content = re.sub(r'赞\s*\[\d+\]', '', content)
    content = re.sub(r'评论\s*\[\d+\]', '', content)
    content = re.sub(r'转发\s*\[\d+\]', '', content)
    content = re.sub(r'来自.*?(?:客户端|$)', '', content)
    content = re.sub(r'\s+', ' ', content).strip()
    return {
        "title": content[:30],
        "content": content,
        "timestamp": datetime.now().isoformat(),
        "tags": [],
        "source": "QQ空间",
        "pics": item.get("images", []),
    }


if __name__ == "__main__":
    uin = sys.argv[1] if len(sys.argv) > 1 else "1318846394"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    print(f"[collect] 目标 QQ: {uin}")
    raw_items = collect(uin, max_pages=pages)

    if raw_items:
        articles = [parse_raw(item) for item in raw_items]
        output = ROOT / "raw" / f"qzone_{uin}.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"[collect] 共 {len(articles)} 条，已保存 {output}")
        for a in articles[:3]:
            print(f"  {a['content'][:60]}...")
    else:
        print("[collect] 无数据")
