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

TEAM_NAMES_EN: Dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
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

TEAM_FULL_NAMES_ZH: Dict[str, str] = {
    "ATL": "亚特兰大老鹰",
    "BOS": "波士顿凯尔特人",
    "BKN": "布鲁克林篮网",
    "CHA": "夏洛特黄蜂",
    "CHI": "芝加哥公牛",
    "CLE": "克利夫兰骑士",
    "DAL": "达拉斯独行侠",
    "DEN": "丹佛掘金",
    "DET": "底特律活塞",
    "GSW": "金州勇士",
    "HOU": "休斯顿火箭",
    "IND": "印第安纳步行者",
    "LAC": "洛杉矶快船",
    "LAL": "洛杉矶湖人",
    "MEM": "孟菲斯灰熊",
    "MIA": "迈阿密热火",
    "MIL": "密尔沃基雄鹿",
    "MIN": "明尼苏达森林狼",
    "NOP": "新奥尔良鹈鹕",
    "NYK": "纽约尼克斯",
    "OKC": "俄克拉荷马城雷霆",
    "ORL": "奥兰多魔术",
    "PHI": "费城76人",
    "PHX": "菲尼克斯太阳",
    "POR": "波特兰开拓者",
    "SAC": "萨克拉门托国王",
    "SAS": "圣安东尼奥马刺",
    "TOR": "多伦多猛龙",
    "UTA": "犹他爵士",
    "WAS": "华盛顿奇才",
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


def team_full_display_name(tricode: str, language: str = "en") -> str:
    """Return the full display name (e.g. 'Los Angeles Lakers' or '洛杉矶湖人')."""
    code = tricode.upper()
    if language == "zh":
        return TEAM_FULL_NAMES_ZH.get(code, TEAM_NAMES_ZH.get(code, code))
    return TEAM_NAMES_EN.get(code, code)



