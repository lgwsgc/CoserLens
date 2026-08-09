"""CoserLens Pipeline - 统一翻译模块

从 cosplay_catalog.json 自动生成英→中翻译映射，
避免在 pipeline_ui.py 和 pipeline_desktop_qt.py 中各维护一份。

catalog 是唯一数据源 (single source of truth)，
添加新角色只需修改 cosplay_catalog.json，翻译自动生效。
"""

import json
from pathlib import Path

import config

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

    _catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

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


# ── 公开接口 ────────────────────────────────────────────
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
