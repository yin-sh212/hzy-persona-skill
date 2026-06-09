"""
自动分类器。

根据文章内容自动判断主分类和标签。
匹配关键词打分，取最高分分类；无命中时归入「随笔」。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CATEGORY_KEYWORDS = {
    "地球科学": [
        "地科", "地学", "地质", "地理", "海洋", "天文", "大气", "地球物理",
        "CESO", "地联", "地学联盟", "地质博物馆", "黄渤海", "自然分界线", "地理生",
        "全国第一", "初赛", "决赛", "银牌", "国决", "普地",
    ],
    "行记": [
        "旅顺", "大连", "周水子", "锦州", "笔架山", "小布达拉宫",
        "无锡", "太湖", "南通", "濠河", "谯楼", "苏州", "上海", "杭州",
        "南洋理工", "俄罗斯", "净月潭", "维多利亚港", "夫子庙",
        "一日三城", "打卡", "踏青", "观山", "过海",
    ],
    "音乐": [
        "邓紫棋", "G.E.M.", "GEM", "孙燕姿", "解解",
        "天黑黑", "遇见", "我怀念的", "逆光", "就在日落以后",
        "演唱会", "大合唱", "华语女歌手",
    ],
    "校园": [
        "吉大", "百团", "社团", "春游", "UNO", "论文", "仓鼠",
        "图书馆", "开学", "军训", "摄协", "天协", "保研", "培养计划",
    ],
    "故土与家": [
        "伴郎", "哥哥", "嫂嫂", "妈妈", "爸爸", "姐姐",
        "生日", "元宵", "春节", "中秋",
        "苏北", "回家", "睢中", "徐州",
    ],
    "旧日": [
        "高考", "强基", "综评", "中科大", "南京大学", "南大", "校测", "冬令营",
        "省二", "物理竞赛", "化学", "通中",
    ],
}

# 平局时的优先级
PRIORITY = ["地球科学", "旧日", "故土与家", "行记", "音乐", "校园", "随笔"]


def classify(text: str) -> tuple[str, list[str]]:
    """
    返回 (主分类, 标签列表)。
    关键词命中数多者胜出，平局按优先级取。
    无命中时返回 ("随笔", [])。
    """
    scores = {}
    tags = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text:
                score += 1
                tags.append(kw)
        if score > 0:
            scores[category] = score

    if not scores:
        return ("随笔", tags)

    # 取最高分，平局按优先级
    max_score = max(scores.values())
    candidates = [c for c, s in scores.items() if s == max_score]
    if len(candidates) == 1:
        return (candidates[0], tags)

    for cat in PRIORITY:
        if cat in candidates:
            return (cat, tags)

    return ("随笔", tags)


if __name__ == "__main__":
    samples = [
        "在旅顺感受黄渤海自然分界线，地理生打卡+1",
        "孙燕姿苏州场！大合唱《遇见》真的太震撼了",
        "百团大战，地联和MM的体验真的很不一样",
        "二十岁生日赶上元宵节，第一次寒假和家人一起过",
        "高考强基差3分进中科大，想起来还是遗憾",
        "买完大疆发现只能吃土了",
    ]
    for text in samples:
        cat, tags = classify(text)
        print(f"[{cat}] {tags[:5]} | {text[:40]}...")
