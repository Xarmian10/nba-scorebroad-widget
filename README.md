# NBA Scoreboard Widget

一个桌面 NBA 比分小组件，提供当天比赛的比分与状态展示，并支持多语言与个性化显示设置。

## 功能

- 当天比赛比分与比赛状态展示
- 中英文切换
- 球员数据查看
- 透明度调整
- `Alt + X` 快捷键显示/隐藏

## 技术说明

- 基于 `nba_api` 实现数据获取

## 启动方式

以下是当前项目内已有的启动方式：

1. 直接运行（开发模式）
   ```bash
   python main.py
   ```

2. 打包并运行（Windows）
   ```bat
   scripts\build.bat
   ```
   打包完成后在 `dist\nba-scoreboard` 中运行生成的可执行文件。

