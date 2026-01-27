from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtGui import QColor

ROOT_DIR = Path(__file__).resolve().parent.parent

# 简易队色映射，可按需补充
TEAM_COLORS: Dict[str, str] = {
    "ATL": "#E03A3E",
    "BOS": "#007A33",
    "BKN": "#000000",
    "CHA": "#1D1160",
    "CHI": "#BA0C2F",
    "CLE": "#860038",
    "DAL": "#00538C",
    "DEN": "#0E2240",
    "DET": "#C8102E",
    "GSW": "#1D428A",
    "HOU": "#CE1141",
    "IND": "#002D62",
    "LAC": "#C8102E",
    "LAL": "#552583",
    "MEM": "#5D76A9",
    "MIA": "#98002E",
    "MIL": "#00471B",
    "MIN": "#0C2340",
    "NOP": "#0C2340",
    "NYK": "#006BB6",
    "OKC": "#007AC1",
    "ORL": "#0077C0",
    "PHI": "#006BB6",
    "PHX": "#1D1160",
    "POR": "#E03A3E",
    "SAC": "#5A2D81",
    "SAS": "#C4CED4",
    "TOR": "#CE1141",
    "UTA": "#002B5C",
    "WAS": "#002B5C",
}

# 若有本地图标，可将 tricode->相对路径填入；不存在时返回 None
TEAM_LOGOS: Dict[str, str] = {
    "ATL": "src/simple_circle_hawks_000.png",
    "BOS": "src/simple_circle_celtics_000.png",
    "BKN": "src/simple_circle_nets_000.png",
    "CHA": "src/simple_circle_hornets_000.png",
    "CHI": "src/simple_circle_bulls_000.png",
    "CLE": "src/simple_circle_cavaliers_000.png",
    "DAL": "src/simple_circle_mavericks_000.png",
    "DEN": "src/simple_circle_nuggets_000.png",
    "DET": "src/simple_circle_pistons_000.png",
    "GSW": "src/simple_circle_warriors_000.png",
    "HOU": "src/simple_circle_rockets_000.png",
    "IND": "src/simple_circle_pacers_000.png",
    "LAC": "src/simple_circle_clippers_000.png",
    "LAL": "src/simple_circle_lakers_000.png",
    "MEM": "src/simple_circle_grizzlies_000.png",
    "MIA": "src/simple_circle_heat_000.png",
    "MIL": "src/simple_circle_bucks_000.png",
    "MIN": "src/simple_circle_timberwolves_000.png",
    "NOP": "src/simple_circle_pelicans_000.png",
    "NYK": "src/simple_circle_knicks_000.png",
    "OKC": "src/simple_circle_thunder_000.png",
    "ORL": "src/simple_circle_magic_000.png",
    "PHI": "src/simple_circle_76ers_000.png",
    "PHX": "src/simple_circle_suns_000.png",
    "POR": "src/simple_circle_trailblazers_000.png",
    "SAC": "src/simple_circle_kings_000.png",
    "SAS": "src/simple_circle_spurs_000.png",
    "TOR": "src/simple_circle_raptors_000.png",
    "UTA": "src/simple_circle_jazz_000.png",
    "WAS": "src/simple_circle_wizards_000.png",
}

TEAM_NAMES_ZH: Dict[str, str] = {
    "ATL": "老鹰",
    "BOS": "凯尔特人",
    "BKN": "篮网",
    "CHA": "黄蜂",
    "CHI": "公牛",
    "CLE": "骑士",
    "DAL": "独行侠",
    "DEN": "掘金",
    "DET": "活塞",
    "GSW": "勇士",
    "HOU": "火箭",
    "IND": "步行者",
    "LAC": "快船",
    "LAL": "湖人",
    "MEM": "灰熊",
    "MIA": "热火",
    "MIL": "雄鹿",
    "MIN": "森林狼",
    "NOP": "鹈鹕",
    "NYK": "尼克斯",
    "OKC": "雷霆",
    "ORL": "魔术",
    "PHI": "76人",
    "PHX": "太阳",
    "POR": "开拓者",
    "SAC": "国王",
    "SAS": "马刺",
    "TOR": "猛龙",
    "UTA": "爵士",
    "WAS": "奇才",
}


def team_color(tricode: str, fallback: str = "#444") -> QColor:
    hex_color = TEAM_COLORS.get(tricode.upper(), fallback)
    return QColor(hex_color)


def team_logo_path(tricode: str) -> Optional[Path]:
    path = TEAM_LOGOS.get(tricode.upper())
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    return candidate if candidate.exists() else None


def team_display_name(tricode: str, language: str = "en") -> str:
    code = tricode.upper()
    if language == "zh":
        return TEAM_NAMES_ZH.get(code, code)
    return code



