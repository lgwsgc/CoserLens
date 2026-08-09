import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOG_PATH = SCRIPT_DIR / "cosplay_catalog.json"
CACHE_DIR = SCRIPT_DIR.parent / ".pipeline_analysis_cache"
_CATALOG_CACHE: dict | None = None

BASE_HASHTAGS = ["#Cosplay", "#Cosplayer", "#shorts"]
MAX_HASHTAGS = 8  # YouTube 标签上限，超过会被截断

# 置信度阈值：角色识别分数判定
CONFIDENCE_HIGH = 0.82   # 中文名完全匹配 → 高置信度
CONFIDENCE_MEDIUM = 0.68  # 别名/partial 匹配 → 中等置信度
CONFIDENCE_CAP = 0.85     # 置信度上限（不过度自信）
CONFIDENCE_THRESHOLD = 0.75  # 低于此值不信任识别结果，触发在线搜索

NOISY_CAPTION_TERMS = [
    "回复",
    "评论",
    "点赞",
    "关注",
    "投稿",
    "摄影",
    "摄像",
    "宝宝",
    "妈妈",
    "粉丝",
    "不好意思",
    "致歉",
    "狗头",
    "笑死",
    "谁懂",
    "纯欲",
    "女友感",
    "成熟女人",
    "不良",
]

STOP_HASHTAGS = {
    "cos",
    "cosplay",
    "二次元",
    "二次元美女cosplay",
    "我的cos女孩",
    "萌",
    "甜妹",
    "御",
    "jk",
    "旗袍",
    "女仆装",
    "翻拍",
    "变装",
    "慢摇",
    "手势舞",
    "卡点舞",
    "转场",
    "运镜",
    "live图",
    "正常游泳衣无不良影响",
    "无不良引导",
}

CAPTION_TRANSLATIONS = {
    "一曲相思": "A Song of Longing",
    "我终于找到所寻之人": "I finally found the one I have been searching for.",
    "江畔何人初见雪": "A snowy riverside cosplay moment.",
    "神女爱世间": "A goddess-inspired cosplay moment.",
    "敦煌神女现世了": "A Dunhuang goddess-inspired look.",
    "一梦入敦煌": "A dreamlike Dunhuang-inspired moment.",
    "大王，不来一曲吗": "A royal dance-inspired moment.",
    "嘴巴再硬 亲起来也是软的": "",
    "今天喝了杯果汁": "",
}

MOMENT_TITLE_HOOKS = {
    "I finally found the one I have been searching for.": "{character} Finally Found the One She Was Looking For",
    "A Song of Longing": "A Song of Longing with {character}",
    "A snowy riverside cosplay moment.": "{character} in a Snowy Riverside Cosplay Moment",
    "A Dunhuang goddess-inspired look.": "Dunhuang Goddess Costume Look in Real Life",
    "A dreamlike Dunhuang-inspired moment.": "A Dreamlike Dunhuang Costume Moment",
    "A royal dance-inspired moment.": "A Royal Dance Costume Moment",
}


def load_catalog() -> dict:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    try:
        _CATALOG_CACHE = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _CATALOG_CACHE = {"characters": [], "sources": []}
    return _CATALOG_CACHE


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def normalize_hashtag(tag: str) -> str:
    return tag.strip().strip("#").lower()


def hashtag_text(hashtags: list[str]) -> set[str]:
    return {normalize_hashtag(tag) for tag in hashtags if tag}


def clean_caption(caption: str) -> str:
    text = re.sub(r"#([^\s#]+)", " ", caption)
    text = re.sub(r"@\S+", " ", text)
    text = re.sub(r"回复\s*@?\S*\s*的评论", " ", text)
    text = re.sub(r"摄影[:：@]\S+", " ", text)
    text = re.sub(r"摄像[:：@]\S+", " ", text)
    text = re.sub(r"[“”\"'~～!！?？。…·,，；;：:]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_")
    return text


def caption_moment_en(caption: str) -> str:
    cleaned = clean_caption(caption)
    if not cleaned:
        return ""
    if any(term in cleaned for term in NOISY_CAPTION_TERMS):
        for source, translated in CAPTION_TRANSLATIONS.items():
            if source in cleaned:
                return translated
        return ""
    for source, translated in CAPTION_TRANSLATIONS.items():
        if source in cleaned:
            return translated
    return ""


def infer_scene(context: dict, text: str) -> dict:
    lowered = text.lower()
    combined = compact_text(text)
    evidence = []
    if any(
        term in combined
        for term in [
            "\u53d8\u88c5",
            "\u53d8\u8eab",
            "\u8f6c\u573a",
            "\u5bf9\u955c",
            "\u955c\u5b50",
            "\u6311\u6218",
            "transformation",
            "transition",
            "mirror challenge",
            "mirror transition",
        ]
    ):
        evidence.append("mirror or transformation transition clue")
        return {
            "kind": "transformation",
            "title_word": "Cosplay Transformation",
            "description": "capturing a fantasy cosplay transformation",
            "evidence": evidence,
        }
    if any(term in combined for term in ["苗疆", "苗家", "民族服饰"]):
        evidence.append("Miao ethnic costume clue")
        return {"kind": "miao", "title_word": "Miao Style Costume", "description": "featuring a Miao-inspired ethnic costume look", "evidence": evidence}
    if any(term in combined for term in ["敦煌", "飞天", "神女", "西域"]):
        evidence.append("Dunhuang or western-region styling clue")
        return {"kind": "dunhuang", "title_word": "Dunhuang Inspired Look", "description": "featuring a Dunhuang-inspired fantasy costume look", "evidence": evidence}
    if any(term in combined for term in ["美人鱼", "mermaid"]):
        evidence.append("mermaid costume clue")
        return {"kind": "mermaid", "title_word": "Mermaid Costume", "description": "featuring a mermaid-inspired costume look", "evidence": evidence}
    if any(term in combined for term in ["漫展", "萤火虫漫展", "cp32", "bw", "bilibiliworld", "chinajoy"]):
        evidence.append("convention/event clue")
        return {"kind": "convention", "title_word": "at Anime Convention", "description": "captured at a live anime and cosplay event", "evidence": evidence}
    if any(term in combined for term in ["水上乐园", "泳装", "游泳衣", "waterpark", "swimsuit"]):
        evidence.append("water park or swimsuit clue")
        return {"kind": "water_park", "title_word": "at Water Park", "description": "filmed in a summer water park setting", "evidence": evidence}
    if any(term in combined for term in ["走秀", "秀场", "猫步", "runway", "catwalk"]):
        evidence.append("runway clue")
        return {"kind": "runway", "title_word": "Cosplay Walk", "description": "captured during a cosplay walk", "evidence": evidence}
    if any(term in combined for term in ["展台", "活动", "试玩会", "庆典", "派对", "event"]):
        evidence.append("live event clue")
        return {"kind": "event", "title_word": "at the Event", "description": "captured at a live cosplay event", "evidence": evidence}
    if "korean" in lowered or "korea" in lowered or "韩国" in text:
        evidence.append("Korea clue")
        return {"kind": "korean", "title_word": "Korean Cosplayer", "description": "featuring a Korean cosplayer at a live event", "evidence": evidence}
    return {"kind": "generic", "title_word": "Cosplay Moment", "description": "filmed in a cinematic short-video style", "evidence": evidence}


def match_alias(alias: str, haystack: str, compact: str, tags: set[str]) -> bool:
    alias_clean = alias.lower().strip()
    if not alias_clean:
        return False
    if normalize_hashtag(alias_clean) in tags:
        return True
    if re.fullmatch(r"[a-z0-9]{1,3}", alias_clean):
        return re.search(rf"(?<![a-z0-9]){re.escape(alias_clean)}(?![a-z0-9])", haystack) is not None
    if " " in alias_clean:
        return alias_clean in haystack
    return compact_text(alias_clean) in compact


def score_character(entry: dict, haystack: str, compact: str, tags: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    evidence = []
    for alias in entry.get("aliases", []):
        if match_alias(alias, haystack, compact, tags):
            if normalize_hashtag(alias) in tags:
                score = max(score, CONFIDENCE_HIGH)      # 标签完全匹配
            else:
                score = max(score, CONFIDENCE_MEDIUM)     # 别名匹配
            evidence.append(f"character clue: {alias}")
            break
    for alias in entry.get("source_aliases", []):
        if match_alias(alias, haystack, compact, tags):
            score += 0.2  # 作品来源匹配加分
            evidence.append(f"source clue: {alias}")
            break
    if entry.get("character_cn") and normalize_hashtag(entry["character_cn"]) in tags:
        score += 0.12  # 中文名标签加分
    if "cos" in haystack or "cosplay" in haystack or "cos" in tags:
        score += 0.05  # cosplay 关键词加分
    return min(score, CONFIDENCE_CAP), evidence


def score_source(entry: dict, haystack: str, compact: str, tags: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    evidence = []
    for alias in entry.get("aliases", []):
        if match_alias(alias, haystack, compact, tags):
            score = CONFIDENCE_MEDIUM
            evidence.append(f"source clue: {alias}")
            break
    if score and ("cos" in haystack or "cosplay" in haystack or "cos" in tags):
        score += 0.05
    return min(score, 0.85), evidence


def title_source_name(source: str) -> str:
    return source.replace("Naraka: Bladepoint", "Naraka Bladepoint").replace("Honkai: Star Rail", "Honkai Star Rail").replace("Reverse: 1999", "Reverse 1999")


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def stable_pick(options: list[str], seed: str) -> str:
    if not options:
        return ""
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def build_hashtags(character_tags: list[str], source: str, scene: dict) -> list[str]:
    scene_tags = []
    if scene["kind"] == "transformation":
        scene_tags = ["#CosplayTransition", "#AnimeCosplay"]
    elif scene["kind"] == "convention":
        scene_tags = ["#AnimeConvention", "#CosplayEvent"]
    elif scene["kind"] == "water_park":
        scene_tags = ["#SwimsuitCosplay", "#WaterPark"]
    elif scene["kind"] in {"runway", "event"}:
        scene_tags = ["#GameCosplay", "#CosplayEvent"]
    elif scene["kind"] in {"miao", "dunhuang", "mermaid"}:
        scene_tags = ["#ChineseCostume", "#CostumeShorts"]
    elif source:
        if any(tag.lower() in {"#donghua", "#animecosplay"} for tag in character_tags):
            scene_tags = ["#AnimeCosplay"]
        else:
            scene_tags = ["#GameCosplay"]
    tags = dedupe(character_tags + BASE_HASHTAGS + scene_tags)
    return tags[:MAX_HASHTAGS]


def build_title(result: dict, scene: dict, moment: str = "", seed: str = "") -> str:
    character = result.get("character")
    source = result.get("source")
    source_title = title_source_name(source or "")
    kind = scene["kind"]
    if moment in MOMENT_TITLE_HOOKS:
        title = MOMENT_TITLE_HOOKS[moment].format(character=character or "Cosplayer")
        return title[:100].rstrip(" |")
    if character and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
        if kind == "transformation":
            title = stable_pick(
                [
                    "Wait... That's Not CGI?",
                    "The Mirror Just Glitched",
                    "She Wasn't There a Second Ago",
                    "This Cosplay Is Breaking Reality",
                    "The Anime Girl Is Looking Back",
                ],
                seed,
            )
        elif kind == "runway":
            title = f"{character} Cosplay Walks In Like the Character"
        elif kind == "convention":
            title = f"{character} Cosplay at Anime Convention"
        elif kind == "water_park":
            title = f"{character} Cosplay at Water Park"
        elif source_title == "Throne of Seal":
            title = stable_pick(
                [
                    "She Just Stole the Entire Scene",
                    "That Entrance Was Everything",
                    "The Main Character Just Arrived",
                    "No One Was Ready for That Entrance",
                    "Don't Blink",
                ],
                seed,
            )
        elif source_title:
            title = stable_pick(
                [
                    f"{character} Cosplay Looks Unreal in Real Life",
                    f"{character} Cosplay Brings the Character to Life",
                    f"This {character} Cosplay Is So Accurate",
                    f"{character} Just Stepped Out of the Screen",
                ],
                seed,
            )
        else:
            title = stable_pick(
                [
                    f"{character} Cosplay Looks Unreal in Real Life",
                    f"{character} Cosplay Brings the Character to Life",
                    f"This {character} Cosplay Is So Accurate",
                ],
                seed,
            )
    elif source:
        title = stable_pick(
            [
                f"This {source_title} Cosplay Looks Unreal",
                f"A Real-Life {source_title} Cosplay Moment",
                f"{source_title} Cosplay Brought to Life",
            ],
            seed,
        )
    elif kind == "convention":
        title = "Amazing Cosplay Moment at Anime Convention"
    elif kind == "water_park":
        title = "Summer Cosplay Moment at the Water Park"
    elif kind == "korean":
        title = "Korean Cosplayer Moment at the Convention"
    elif kind == "miao":
        title = "Miao Style Costume Look in Real Life"
    elif kind == "dunhuang":
        title = "Dunhuang Inspired Costume Look in Real Life"
    elif kind == "mermaid":
        title = "Mermaid Costume Moment in Real Life"
    else:
        title = stable_pick(
            [
                "Beautiful Cosplay Moment in Real Life",
                "This Cosplay Look Is Stunning",
                "A Cinematic Cosplay Moment in Real Life",
            ],
            seed,
        )
    return title[:100].rstrip(" |")


def build_description(result: dict, scene: dict, moment: str, tags: list[str]) -> str:
    character = result.get("character")
    source = result.get("source")
    lines = []
    if character and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
        if scene["kind"] == "transformation" and source:
            lines.append(
                f"One touch of the mirror, and {character} suddenly feels real. "
                f"A fantasy cosplay transformation inspired by {source}."
            )
        elif scene["kind"] == "transformation":
            lines.append(f"One touch of the mirror, and {character} suddenly feels real.")
        elif source:
            if source == "Throne of Seal":
                lines.append(
                    f"She didn't enter the scene. She stepped out of the anime. "
                    f"{character} from Throne of Seal is standing in the real world. "
                    "Did you recognize her before the hashtags?"
                )
            else:
                lines.append(f"A short cosplay moment featuring {character} from {source}, {scene['description']}.")
        else:
            lines.append(f"A short cosplay moment featuring {character}, {scene['description']}.")
    elif source:
        lines.append(f"A real-life cosplay short inspired by {source}, {scene['description']}.")
    elif scene["kind"] == "water_park":
        lines.append("A summer cosplay short filmed at a water park.")
    elif scene["kind"] == "convention":
        lines.append("A real-life cosplay moment captured at an anime convention.")
    elif scene["kind"] in {"miao", "dunhuang", "mermaid"}:
        lines.append(f"A cinematic short {scene['description']}.")
    else:
        lines.append("A real-life cosplay short filmed in a cinematic style.")
    if moment:
        lines.append(f"Moment: {moment}")
    if character and result.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
        lines.append(f"Character: {character}")
    if source:
        lines.append(f"Source: {source}")
    lines.extend(["", "Subscribe for more real cosplay moments.", "", " ".join(tags)])
    return "\n".join(lines)


def best_local_match(context: dict) -> dict:
    catalog = load_catalog()
    raw_text = " ".join(
        [
            context.get("search_text", ""),
            context.get("caption", ""),
            " ".join(context.get("hashtags", [])),
        ]
    )
    haystack = raw_text.lower()
    compact = compact_text(raw_text)
    tags = hashtag_text(context.get("hashtags", []))

    best = {"confidence": 0.0, "evidence": []}
    for entry in catalog.get("characters", []):
        score, evidence = score_character(entry, haystack, compact, tags)
        if score > best["confidence"]:
            best = {
                "character": entry.get("character_en", ""),
                "source": entry.get("source_en", ""),
                "tags": entry.get("hashtags", []),
                "confidence": score,
                "evidence": evidence,
                "match_type": "character",
            }
    if best["confidence"] >= CONFIDENCE_THRESHOLD:
        return best

    source_best = {"confidence": 0.0, "evidence": []}
    for entry in catalog.get("sources", []):
        score, evidence = score_source(entry, haystack, compact, tags)
        if score > source_best["confidence"]:
            source_best = {
                "character": "",
                "source": entry.get("source_en", ""),
                "tags": entry.get("hashtags", []),
                "confidence": score,
                "evidence": evidence,
                "match_type": "source",
            }
    return best if best["confidence"] >= source_best["confidence"] else source_best


def extract_search_terms(context: dict) -> list[str]:
    terms = []
    for tag in context.get("hashtags", []):
        clean = tag.strip().strip("#")
        if not clean or normalize_hashtag(clean) in STOP_HASHTAGS:
            continue
        if re.fullmatch(r"[A-Za-z0-9_ -]{2,40}", clean) or re.search(r"[\u4e00-\u9fff]", clean):
            terms.append(clean)
    return dedupe(terms)[:5]


def web_search_snippet(query: str, timeout: int = 8) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = re.sub(r"[^A-Za-z0-9_-]+", "_", query)[:100]
    cache_path = CACHE_DIR / f"search_{cache_key}.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.warning("在线搜索失败 (query=%s): %s", query, exc)
        return ""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:4000]
    cache_path.write_text(text, encoding="utf-8")
    return text


def online_candidate(context: dict) -> dict:
    best = {"confidence": 0.0, "evidence": []}
    for term in extract_search_terms(context):
        query = f"{term} cosplay character English name"
        snippet = web_search_snippet(query)
        if snippet:
            checked_context = {
                "caption": term,
                "hashtags": [term],
                "search_text": f"{term} {snippet}",
            }
            candidate = best_local_match(checked_context)
            if candidate.get("confidence", 0.0) > best.get("confidence", 0.0):
                candidate["confidence"] = min(candidate["confidence"], 0.78)  # 在线结果置信度上限低于本地
                candidate["evidence"] = dedupe(candidate.get("evidence", []) + [f"web search checked: {term}"])
                best = candidate
            elif best["confidence"] == 0:
                best["evidence"].append(f"web search checked: {term}")
    return best


def analyze_context(context: dict, allow_online: bool = False) -> dict:
    result = best_local_match(context)
    raw_text = " ".join([context.get("search_text", ""), context.get("caption", ""), " ".join(context.get("hashtags", []))])
    scene = infer_scene(context, raw_text)
    result.setdefault("character", "")
    result.setdefault("source", "")
    result.setdefault("tags", [])
    result.setdefault("confidence", 0.0)
    result.setdefault("evidence", [])
    result["evidence"] = dedupe(result["evidence"] + scene.get("evidence", []))
    if allow_online and result["confidence"] < CONFIDENCE_THRESHOLD:
        web_result = online_candidate(context)
        if web_result.get("confidence", 0.0) > result.get("confidence", 0.0):
            result = web_result
            result["evidence"] = dedupe(result.get("evidence", []) + scene.get("evidence", []))
        else:
            result["evidence"] = dedupe(result["evidence"] + web_result.get("evidence", []))
    tags = build_hashtags(result.get("tags", []), result.get("source", ""), scene)
    moment = caption_moment_en(context.get("caption", ""))
    title = build_title(result, scene, moment, raw_text)
    description = build_description(result, scene, moment, tags)
    result.update(
        {
            "scene": scene["kind"],
            "moment": moment,
            "title": title,
            "description": description,
            "hashtags": tags,
        }
    )
    return result


def parse_path_context(path: Path) -> dict:
    stem = path.stem
    marker = "-视频-"
    tail = stem.split(marker, 1)[1] if marker in stem else stem
    if marker in stem and "-" in tail:
        _, caption = tail.split("-", 1)
    else:
        caption = tail
    caption = re.sub(r"^\d{4}[-_.]\d{1,2}[-_.]\d{1,2}\s+\d{1,2}[.:\-]\d{1,2}[.:\-]\d{1,2}[-_\s]*", "", caption)
    hashtags = re.findall(r"#([^\s#]+)", caption)
    return {
        "caption": clean_caption(caption),
        "hashtags": hashtags,
        "search_text": " ".join([stem, caption, " ".join(hashtags)]),
    }


def draft_metadata_for_path(path: Path, context: dict | None = None, allow_online: bool = False) -> dict:
    analysis = analyze_context(context or parse_path_context(path), allow_online=allow_online)
    return {
        "title": analysis["title"],
        "description": analysis["description"],
        "analysis": {
            "character": analysis.get("character", ""),
            "source": analysis.get("source", ""),
            "confidence": analysis.get("confidence", 0.0),
            "scene": analysis.get("scene", ""),
            "evidence": analysis.get("evidence", []),
        },
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate CoserLens English metadata from weak cosplay clues.")
    parser.add_argument("video", type=Path)
    parser.add_argument("--online", action="store_true", help="Collect web-search evidence for low-confidence matches.")
    args = parser.parse_args()
    metadata = draft_metadata_for_path(args.video, allow_online=args.online)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
