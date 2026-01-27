from __future__ import annotations

from typing import Optional

from app.ui.scoreboard_widget import ScoreboardWidget


class BroadcastScoreboardWidget(ScoreboardWidget):
    """Broadcast 专用比分控件，布局与主题独立于 dark/light。"""

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)
        self.set_layout_mode("broadcast")






