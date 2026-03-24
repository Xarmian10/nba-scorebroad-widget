# NBA Scoreboard Widget

ESPN/TNT 风格的桌面 NBA 实时记分牌小组件，基于 PySide6 (Qt 6) 构建。

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Qt](https://img.shields.io/badge/PySide6-Qt%206-green)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

## 功能特性

### 记分牌
- ESPN/TNT 体育转播风格 UI，球队主题色自适应
- 紧凑模式：球队名、比分、节数、暂停数
- 展开模式（点击展开）：每节得分 + 主客队全体球员数据
- 得分变化滚动动画
- 比赛切换（右键菜单选择当天其他场次）

### 球员高阶数据
- 点击球员名字弹出详情面板
- 球员头像（NBA CDN）
- 高阶数据：TS%、eFG%、FG%、3P%、FT%、+/-、上场时间、失误
- 投篮位置图（Shot Chart）：半场可视化，区分命中/未中

### 国际化
- 中英文切换（右键菜单）
- 中文模式：球队全名、位置翻译、高阶数据标签、NBA 官方中文字体
- 数字始终使用 NBA 缩窄字体（Bahnschrift Condensed）

### 桌面集成
- 无边框置顶窗口，可自由拖拽
- 滚轮调节透明度（30%–100%）
- `Alt + X` 全局热键显示/隐藏
- 最小化自动收入系统托盘
- 三种主题：Dark / Light / Broadcast

## 技术栈

| 组件 | 技术 |
|------|------|
| GUI 框架 | PySide6-Essentials (Qt 6) |
| 数据源 | nba_api（Live API + PlayByPlay） |
| 球员头像 | NBA CDN |
| 全局热键 | keyboard |
| 打包 | PyInstaller |

## 快速开始

### 环境要求

- Python 3.12+
- Windows 10/11

### 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install PySide6-Essentials keyboard nba_api
```

### 运行

```bash
python main.py
```

### 打包（Windows）

```bat
scripts\build.bat
```

打包完成后在 `dist\nba-scoreboard` 中运行生成的可执行文件。

## 操作说明

| 操作 | 功能 |
|------|------|
| 左键点击记分栏 | 展开/收起球员数据面板 |
| 右键点击 | 打开设置菜单（选场次/主题/语言/置顶/退出） |
| 滚轮 | 调节窗口透明度 |
| 拖拽 | 任意位置移动窗口 |
| Alt + X | 显示/隐藏窗口 |
| 点击球员名字 | 弹出球员高阶数据面板 |

## 项目结构

```
nba-widgets-windows/
├── main.py                    # 入口
├── app/
│   ├── models.py              # 数据模型
│   ├── resources.py           # 球队资源（颜色、Logo、名称）
│   ├── services.py            # NBA API 数据服务
│   └── ui/
│       ├── main_window.py     # 主窗口
│       ├── scoreboard_widget.py    # 记分牌控件
│       ├── player_detail_widget.py # 球员详情面板
│       └── poll_worker.py     # 后台轮询
├── src/                       # 球队 Logo 资源
└── scripts/
    └── build.bat              # 打包脚本
```
