from __future__ import annotations

from typing import Optional

from app.ui.scoreboard_widget import ScoreboardWidget


class BroadcastScoreboardWidget(ScoreboardWidget):
    """兼容性别名——所有主题现在共用 ScoreboardWidget 的 ESPN/TNT 布局。"""

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)
