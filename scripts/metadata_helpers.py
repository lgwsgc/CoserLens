"""元数据生成 — 角色识别、标题/描述生成、文案校验。

从 pipeline_ui.py 抽离，消除 pipeline_ui 中混杂的业务逻辑。
"""

import json
import logging
import re
from pathlib import Path

import cosplay_metadata_analyzer
import state

logger = logging.getLogger(__name__)


# ── 角色匹配规则 ──────────────────────────────────────────
CHARACTER_RULES = [
    {
        "patterns": ["顾清寒", "guqinghan", "gu qinghan"],
        "character": "Gu Qinghan",
        "source_patterns": ["永劫无间", "naraka"],
        "source": "Naraka: Bladepoint",
        "title": "Gu Qinghan Cosplay Looks Unreal in Real Life",
        "tags": ["#GuQinghan", "#NarakaBladepoint", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["公孙离", "gongsunli", "gongsun li"],
        "character": "Gongsun Li",
        "source_patterns": ["王者荣耀", "honor of kings"],
        "source": "Honor of Kings",
        "title": "Gongsun Li Cosplay Brings the Character to Life",
        "tags": ["#GongsunLi", "#HonorOfKings", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["萧薰儿", "薰儿", "xiao xun", "xiaoxun"],
        "character": "Xiao Xun'er",
        "source_patterns": ["斗破", "donghua"],
        "source": "Donghua",
        "title": "Xiao Xun'er Cosplay Looks Real in Real Life",
        "tags": ["#XiaoXuner", "#Donghua", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["迦南", "canaan"],
        "character": "Canaan",
        "source_patterns": ["永劫无间", "naraka"],
        "source": "Naraka: Bladepoint",
        "title": "Canaan Cosplay Looks Unreal in Real Life",
        "tags": ["#Canaan", "#NarakaBladepoint", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["露娜", "luna"],
        "character": "Luna",
        "source_patterns": ["王者荣耀", "honor of kings"],
        "source": "Honor of Kings",
        "title": "Luna Cosplay Looks Unreal in Real Life",
        "tags": ["#Luna", "#HonorOfKings", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["殷紫萍", "yin ziping", "yinziping"],
        "character": "Yin Ziping",
        "source_patterns": ["永劫无间", "naraka"],
        "source": "Naraka: Bladepoint",
        "title": "Yin Ziping Cosplay Looks Unreal in Real Life",
        "tags": ["#YinZiping", "#NarakaBladepoint", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["长离", "changli"],
        "character": "Changli",
        "source_patterns": ["鸣潮", "wuthering waves"],
        "source": "Wuthering Waves",
        "title": "Changli Cosplay Looks Unreal in Real Life",
        "tags": ["#Changli", "#WutheringWaves", "#Cosplay", "#shorts"],
    },
]


CAPTION_TRANSLATIONS = {
    "一曲相思": "A Song of Longing",
    "我终于找到所寻之人": "I finally found the one I've been searching for.",
    "长沙夏天的快乐是大王山给的": "Summer fun at Dawangshan in Changsha.",
    "长沙湘江水上乐园": "Changsha Xiangjiang Water Park.",
    "泳装cos": "swimsuit cosplay",
    "正常泳装穿搭": "swimsuit outfit",
}


def clean_filename_text(path: Path) -> str:
    """从文件名中移除日期、括号等噪音，返回干净的文本。"""
    text = path.stem
    text = re.sub(r"\d{4}[-_.年]\d{1,2}[-_.月]\d{1,2}.*?(视频|-)", " ", text)
    text = re.sub(r"[#【】\[\]（）()]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_download_desc(path: Path) -> str:
    """读取 TikTokDownloader 生成的 download_meta.json 中的视频描述。"""
    meta_path = path.parent / "download_meta.json"
    if not meta_path.exists():
        return ""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    output_file = str(data.get("output_file") or "").strip()
    if output_file:
        try:
            if Path(output_file).resolve() != path.resolve():
                return ""
        except Exception:
            return ""
    elif data.get("aweme_id"):
        # Single-work downloads write per-video metadata. Batch folders may contain
        # a stale or unrelated sidecar, so do not trust it unless it names this file.
        return ""
    return str(data.get("desc") or "").strip()


def parse_filename_context(path: Path) -> dict:
    """从文件名和 sidecar 元数据中提取创作者、字幕、标签等上下文。"""
    stem = path.stem
    sidecar_desc = read_download_desc(path)
    context = {
        "creator": "",
        "caption": "",
        "caption_en": "",
        "hashtags": [],
        "search_text": stem,
    }
    marker = "-视频-"
    tail = stem.split(marker, 1)[1] if marker in stem else stem
    if marker in stem and "-" in tail:
        creator, caption = tail.split("-", 1)
        context["creator"] = creator.strip()
    else:
        caption = tail
    if sidecar_desc:
        caption = f"{caption} {sidecar_desc}"
    caption = re.sub(r"^\d{4}[-_.]\d{1,2}[-_.]\d{1,2}\s+\d{1,2}[.:\-]\d{1,2}[.:\-]\d{1,2}[-_\s]*", "", caption)
    hashtags = re.findall(r"#([^\s#]+)", caption)
    caption_text = re.sub(r"#([^\s#]+)", " ", caption)
    caption_text = re.sub(r"[~！？.?]+$", "", caption_text)
    caption_text = re.sub(r"\s+", " ", caption_text).strip(" -_")
    context["caption"] = caption_text
    context["hashtags"] = hashtags
    translated_parts = []
    for source, translated in CAPTION_TRANSLATIONS.items():
        if caption_text and source in caption_text and translated not in translated_parts:
            translated_parts.append(translated)
    context["caption_en"] = " ".join(translated_parts)
    context["search_text"] = " ".join([stem, sidecar_desc, caption_text, " ".join(hashtags)])
    return context


def infer_title_from_context(context: dict) -> str | None:
    """根据字幕/标签中的关键词推断场景化标题。"""
    combined = " ".join([context.get("caption", ""), " ".join(context.get("hashtags", []))])
    lowered = combined.lower()
    if "永劫无间" in combined or "naraka" in lowered:
        return "This Naraka Bladepoint Cosplay Looks Unreal"
    if "王者荣耀" in combined or "honor of kings" in lowered:
        return "This Honor of Kings Cosplay Looks Unreal"
    if "漫展" in combined or "bw" in lowered or "bilibiliworld" in lowered:
        return "Amazing Cosplay Moment at Anime Convention"
    if "韩国" in combined or "korea" in lowered or "korean" in lowered:
        return "Korean Cosplayer Moment at the Convention"
    if "苗疆" in combined or "民族服饰" in combined or "苗族" in combined:
        return "Miao Style Costume Look in Real Life"
    if "接财神" in combined or "财神" in combined:
        return "Cosplayer Welcomes the God of Wealth"
    if "泳装" in combined and ("水上乐园" in combined or "湘江" in combined):
        return "Summer Cosplay Moment at the Water Park"
    if "泳装" in combined:
        return "Swimsuit Cosplay Look in Real Life"
    if "水上乐园" in combined or "湘江" in combined:
        return "Summer Cosplay Moment at the Water Park"
    return None


def find_rule(text: str) -> dict | None:
    """在 CHARACTER_RULES 中查找匹配的角色规则。"""
    lowered = text.lower()
    for rule in CHARACTER_RULES:
        if any(pattern.lower() in lowered for pattern in rule["patterns"]):
            return rule
    return None


def make_description(rule: dict | None, fallback_title: str, context: dict | None = None) -> str:
    """根据角色规则和上下文生成 YouTube 视频描述。"""
    context = context or {}
    moment = context.get("caption_en") or ""
    combined = " ".join([context.get("caption", ""), " ".join(context.get("hashtags", []))])
    if rule:
        lines = [f"Real-life {rule['character']} cosplay short filmed in a cinematic style."]
        if moment:
            lines.append(f"Moment: {moment}")
        lines.append(f"Character: {rule['character']}")
        if rule.get("source"):
            lines.append(f"Source: {rule['source']}")
        lines.extend(["", "Subscribe for more real cosplay moments.", "", " ".join(rule["tags"])])
        return "\n".join(lines)
    if "泳装" in combined and ("水上乐园" in combined or "湘江" in combined):
        return "\n".join(
            [
                "Real-life swimsuit cosplay short filmed at a water park.",
                "Location: Changsha Xiangjiang Water Park" if "湘江" in combined else "Location: Water park",
                "Style: Swimsuit cosplay / summer water park",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#SwimsuitCosplay #WaterPark #Cosplay #shorts",
            ]
        )
    if "泳装" in combined:
        return "\n".join(
            [
                "Real-life swimsuit cosplay short filmed in a cinematic style.",
                "Style: Swimsuit cosplay",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#SwimsuitCosplay #Cosplay #Cosplayer #shorts",
            ]
        )
    if "永劫无间" in combined or "naraka" in combined.lower():
        return "\n".join(
            [
                "Real-life Naraka Bladepoint cosplay short filmed in a cinematic style.",
                "Source: Naraka: Bladepoint",
                "",
                "Subscribe for more real game cosplay moments.",
                "",
                "#NarakaBladepoint #GameCosplay #Cosplay #shorts",
            ]
        )
    if "王者荣耀" in combined or "honor of kings" in combined.lower():
        return "\n".join(
            [
                "Real-life Honor of Kings cosplay short filmed in a cinematic style.",
                "Source: Honor of Kings",
                "",
                "Subscribe for more real game cosplay moments.",
                "",
                "#HonorOfKings #GameCosplay #Cosplay #shorts",
            ]
        )
    if "漫展" in combined or "bw" in combined.lower() or "bilibiliworld" in combined.lower():
        return "\n".join(
            [
                "Real-life anime convention cosplay short filmed on site.",
                "Scene: Convention floor cosplay showcase",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#AnimeConvention #Cosplay #Cosplayer #shorts",
            ]
        )
    if "韩国" in combined or "korea" in combined.lower() or "korean" in combined.lower():
        return "\n".join(
            [
                "Real-life Korean cosplayer short filmed in a cinematic style.",
                "Scene: Cosplayer showcase",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#KoreanCosplayer #Cosplay #Cosplayer #shorts",
            ]
        )
    return "\n".join(
        [line for line in [
            "Real-life cosplayer showcase filmed in a cinematic style.",
            f"Moment: {moment}" if moment else "",
            "",
            "Subscribe for more real cosplay moments.",
            "",
            "#Cosplay #Cosplayer #CosplayShorts #shorts",
        ] if line or line == ""]
    )


def draft_metadata(path: Path, override: dict | None = None, allow_online: bool = False) -> dict:
    """为视频文件生成标题和描述草稿。

    优先使用 cosplay_metadata_analyzer 的智能分析，
    失败时回退到基于文件名的规则匹配。
    """
    context = parse_filename_context(path)
    try:
        metadata = cosplay_metadata_analyzer.draft_metadata_for_path(
            path,
            context=context,
            allow_online=allow_online,
        )
        if override:
            metadata.update({k: v for k, v in override.items() if k in ("title", "description")})
        return metadata
    except Exception as exc:
        logger.warning("元数据分析失败，使用回退逻辑 (%s): %s", path.name, exc)

    text = clean_filename_text(path)
    rule = find_rule(context["search_text"])
    title = f"{rule['character']} Cosplay Looks Unreal in Real Life" if rule else "Beautiful Cosplay Moment in Real Life"
    inferred_title = infer_title_from_context(context) if not rule else None
    if inferred_title:
        title = inferred_title
    elif not rule and context.get("caption_en"):
        title = context["caption_en"].rstrip(".")
    description = make_description(rule, title, context)
    metadata = {"title": title, "description": description}
    if override:
        metadata.update({k: v for k, v in override.items() if k in ("title", "description")})
    return metadata


def validate_publish_copy(title: str, description: str) -> None:
    """校验标题/描述不包含弱回退词（如 Unknown）。"""
    combined = f"{title}\n{description}".lower()
    blocked = [
        "unknown",
        "角色未知",
        "real cosplay moment | cosplay short",
    ]
    for term in blocked:
        if term.lower() in combined:
            raise ValueError(
                "Title/description still contains a weak fallback term. Regenerate or edit it before uploading."
            )
