"""CoserLens Pipeline - 统一翻译模块

从 cosplay_catalog.json 自动生成英→中翻译映射，
避免在 pipeline_ui.py 和 pipeline_desktop_qt.py 中各维护一份。

catalog 是唯一数据源 (single source of truth)，
添加新角色只需修改 cosplay_catalog.json，翻译自动生效。
"""

import json
import logging
import re
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# ── 加载角色数据库 ──────────────────────────────────────
_catalog: dict = {}
_char_en_to_cn: dict[str, str] = {}
_char_cn_to_en: dict[str, str] = {}
_source_en_to_cn: dict[str, str] = {}
_source_cn_to_en: dict[str, str] = {}


def _load_catalog():
    """加载 cosplay_catalog.json，构建翻译映射"""
    global _catalog, _char_en_to_cn, _char_cn_to_en, _source_en_to_cn, _source_cn_to_en

    catalog_path = config.CATALOG_PATH
    if not catalog_path.exists():
        return

    try:
        _catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load cosplay_catalog.json: %s", exc)
        return

    _char_en_to_cn = {}
    _char_cn_to_en = {}
    for char in _catalog.get("characters", []):
        en = char.get("character_en", "")
        cn = char.get("character_cn", "")
        if en and cn:
            _char_en_to_cn[en] = cn
            _char_cn_to_en[cn] = en

    _source_en_to_cn = {}
    _source_cn_to_en = {}
    for src in _catalog.get("sources", []):
        en = src.get("source_en", "")
        cn = src.get("source_cn", "")
        if en and cn:
            _source_en_to_cn[en] = cn
            _source_cn_to_en[cn] = en
    # 角色条目里也可能带 source 信息
    for char in _catalog.get("characters", []):
        en = char.get("source_en", "")
        cn = char.get("source_cn", "")
        if en and cn and en not in _source_en_to_cn:
            _source_en_to_cn[en] = cn
            _source_cn_to_en[cn] = en


_load_catalog()


# ── 基础翻译接口 ────────────────────────────────────────
def character_en_to_cn(name: str) -> str:
    """英文名 → 中文名，找不到返回原名"""
    return _char_en_to_cn.get(name, name)


def character_cn_to_en(name: str) -> str:
    """中文名 → 英文名，找不到返回原名"""
    return _char_cn_to_en.get(name, name)


def source_en_to_cn(name: str) -> str:
    """英文作品名 → 中文作品名，找不到返回原名"""
    return _source_en_to_cn.get(name, name)


def source_cn_to_en(name: str) -> str:
    """中文作品名 → 英文作品名，找不到返回原名"""
    return _source_cn_to_en.get(name, name)


def all_characters() -> list[dict]:
    """返回所有角色数据"""
    return _catalog.get("characters", [])


def all_sources() -> list[dict]:
    """返回所有作品数据"""
    return _catalog.get("sources", [])


# ── UI 文案翻译（英→中）────────────────────────────────

# 精确匹配的整行翻译
_LINE_EXACT = {
    "Real-life cosplay short filmed in a cinematic style.": "真实 Cosplay 短视频，电影感拍摄。",
    "Real-life swimsuit cosplay short filmed in a cinematic style.": "真实泳装 Cosplay 短视频，电影感拍摄。",
    "Real-life swimsuit cosplay short filmed at a water park.": "真实泳装 Cosplay 短视频，在水上乐园拍摄。",
    "Subscribe for more real cosplay moments.": "订阅获取更多真实 Cosplay 瞬间。",
    "Style: Swimsuit cosplay": "风格：泳装 Cosplay",
    "Style: Swimsuit cosplay / summer water park": "风格：泳装 Cosplay / 夏日水上乐园",
    "Location: Water park": "地点：水上乐园",
    "Location: Changsha Xiangjiang Water Park": "地点：长沙湘江水上乐园",
    "Real Cosplay Moment | Cosplay Short": "真实 Cosplay 瞬间 | Cosplay 短视频",
    "Swimsuit Cosplay at Water Park | Cosplay Short": "水上乐园泳装 Cosplay | Cosplay 短视频",
    "Swimsuit Cosplay Look | Cosplay Short": "泳装 Cosplay 造型 | Cosplay 短视频",
    "Water Park Cosplay Moment | Cosplay Short": "水上乐园 Cosplay 瞬间 | Cosplay 短视频",
}

# 标题精确匹配
_TITLE_EXACT = {
    "Wait... That's Not CGI?": "等等，这不是 CGI？",
    "The Mirror Just Glitched": "镜子刚刚卡出了一个动画世界",
    "She Wasn't There a Second Ago": "一秒前她还不在这里",
    "This Cosplay Is Breaking Reality": "这个 Cosplay 快把现实搞坏了",
    "The Anime Girl Is Looking Back": "动画里的女孩正在回头看我",
    "She Just Stole the Entire Scene": "她一出场就抢走了全场焦点",
    "That Entrance Was Everything": "这个出场太绝了",
    "The Main Character Just Arrived": "主角登场了",
    "No One Was Ready for That Entrance": "没有人能准备好这个出场",
    "Don't Blink": "别眨眼",
}

# 标题中的短语替换
_TITLE_REPLACEMENTS = {
    "Battle Through the Heavens": "斗破苍穹",
    "Honor of Kings": "王者荣耀",
    "Naraka Bladepoint": "永劫无间",
    "Naraka: Bladepoint": "永劫无间",
    "Wuthering Waves": "鸣潮",
    "Honkai Star Rail": "崩坏星穹铁道",
    "Genshin Impact": "原神",
    "League of Legends": "英雄联盟",
    "Cosplay Brought to Life": "Cosplay 真人还原",
    "Cosplay Brings the Character to Life": "Cosplay 把角色带到现实",
    "Just Stepped Out of the Screen": "像从屏幕里走出来",
    "This ": "这个 ",
    " Is So Accurate": " 还原度很高",
    "Real Cosplay Moment": "真实 Cosplay 瞬间",
    "Cosplay Short": "Cosplay 短视频",
    "Honor of Kings Short": "王者荣耀短视频",
    "Naraka Bladepoint Short": "永劫无间短视频",
    "Game Cosplay Short": "游戏 Cosplay 短视频",
    "Donghua Short": "国漫短视频",
    "Looks Unreal in Real Life": "真人还原感很强",
    "Looks Real": "还原感很强",
    "Cosplay Walk": "Cosplay 走秀",
    "Cosplay Looks Unreal": "Cosplay 还原度很高",
    "Cosplay": "Cosplay",
    "Short": "短视频",
}

# hashtag 翻译映射
_HASHTAG_MAP = {
    "Cosplay": "Cosplay",
    "Cosplayer": "Coser",
    "AnimeCosplay": "动漫 Cosplay",
    "shorts": "Shorts",
    "SwimsuitCosplay": "泳装 Cosplay",
    "WaterPark": "水上乐园",
    "HonorOfKings": "王者荣耀",
    "NarakaBladepoint": "永劫无间",
    "WutheringWaves": "鸣潮",
    "GameCosplay": "游戏 Cosplay",
    "Donghua": "国漫",
    "XiaoXuner": "萧薰儿",
    "ChineseCostume": "中国风造型",
    "CostumeShorts": "服饰短视频",
    "HonkaiStarRail": "崩坏星穹铁道",
    "GenshinImpact": "原神",
    "LeagueOfLegends": "英雄联盟",
    "Ahri": "阿狸",
    "ZenlessZoneZero": "绝区零",
    "BlueArchive": "蔚蓝档案",
    "AzurLane": "碧蓝航线",
    "IcePrincess": "冰公主",
    "YeLuoli": "叶罗丽",
    "CosplayTransition": "Cosplay 变装转场",
    "ShengCaier": "圣采儿",
    "ThroneOfSeal": "神印王座",
}


def translate_source_name(text: str) -> str:
    """翻译作品名，"Donghua" 特殊处理为国漫"""
    if text == "Donghua":
        return "国漫"
    return source_en_to_cn(text)


def translate_hashtag(tag: str) -> str:
    """翻译单个 hashtag"""
    clean = tag.lstrip("#")
    return _HASHTAG_MAP.get(clean, clean)


def translate_title_terms(text: str) -> str:
    """翻译标题中的英文术语为中文"""
    if text in _TITLE_EXACT:
        return _TITLE_EXACT[text]
    translated = text
    for source, target in _TITLE_REPLACEMENTS.items():
        translated = translated.replace(source, target)
    # 角色名替换：从 catalog 动态获取
    for char in all_characters():
        en = char.get("character_en", "")
        cn = char.get("character_cn", "")
        if en and cn:
            translated = translated.replace(en, cn)
    return translated


def translate_english_line(line: str) -> str:
    """将一行英文文案翻译为中文（用于 UI 中的中文参考显示）。"""
    text = line.strip()
    if not text:
        return ""
    if text in _LINE_EXACT:
        return _LINE_EXACT[text]
    # 正则模式匹配
    inspired_match = re.fullmatch(
        r"A real-life cosplay short inspired by (.+), filmed in a cinematic short-video style\.",
        text,
    )
    if inspired_match:
        source = translate_source_name(inspired_match.group(1))
        return f"真实 Cosplay 短视频，灵感来自 {source}，电影感短视频风格。"
    featuring_match = re.fullmatch(
        r"A short cosplay moment featuring (.+) from (.+), filmed in a cinematic short-video style\.",
        text,
    )
    if featuring_match:
        character = character_en_to_cn(featuring_match.group(1))
        source = translate_source_name(featuring_match.group(2))
        return f"{character} Cosplay 瞬间，角色来自 {source}，电影感短视频风格。"
    transformation_match = re.fullmatch(
        r"One touch of the mirror, and (.+) suddenly feels real\. A fantasy cosplay transformation inspired by (.+)\.",
        text,
    )
    if transformation_match:
        character = character_en_to_cn(transformation_match.group(1))
        source = translate_source_name(transformation_match.group(2))
        return f"轻触镜子，{character}就像真的走到了现实中。一段灵感来自 {source} 的幻想 Cosplay 变装视频。"
    throne_match = re.fullmatch(
        r"A real-life (.+) cosplay from Throne of Seal, captured in a cinematic walk\.",
        text,
    )
    if throne_match:
        character = character_en_to_cn(throne_match.group(1))
        return f"她不是走进了画面，她是从动画里走出来的。{character}来自《神印王座》，现在真的出现在现实中。你是看到标签前认出她的吗？"
    if text.startswith("Real-life ") and " cosplay short filmed in a cinematic style." in text:
        name = text.removeprefix("Real-life ").removesuffix(" cosplay short filmed in a cinematic style.")
        return f"真实 {character_en_to_cn(name)} Cosplay 短视频，电影感拍摄。"
    if text.startswith("Character: "):
        return "角色：" + character_en_to_cn(text.removeprefix("Character: "))
    if text.startswith("Source: "):
        return "出处：" + translate_source_name(text.removeprefix("Source: "))
    if text.startswith("Moment: "):
        return "瞬间：" + text.removeprefix("Moment: ")
    if text.startswith("#"):
        return "标签：" + "、".join(translate_hashtag(tag) for tag in text.split())
    return translate_title_terms(text)


def translate_upload_copy(title: str, description: str) -> str:
    """将标题和描述翻译为中文参考文本。"""
    lines = []
    if title:
        lines.append(f"中文标题：{translate_english_line(title)}")
    if description:
        translated = [translate_english_line(line) for line in description.splitlines()]
        lines.extend(["", "中文说明：", *translated])
    return "\n".join(lines) if lines else "中文参考：-"
