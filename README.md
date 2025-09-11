# JNTMbot - GTAOL 德瑞差事自动化脚本

![License](https://img.shields.io/github/license/shibeta/JNTMbot_python)
![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)
![Node.js Version](https://img.shields.io/badge/node.js-22+-green.svg)

本项目是一个基于 Python 和 Node.js 的德瑞 BOT 挂机脚本。

---

## 目录

-   [🌟 主要功能](#-主要功能)
-   [🔧 环境要求](#-环境要求)
-   [🚀 安装与运行](#-安装与运行)
-   [🛠️ 使用说明](#️-使用说明)
    -   [1. 配置文件 (`config.yaml`)](#1-配置文件-configyaml)
    -   [2. 游戏内设置](#2-游戏内设置)
    -   [3. 程序操作](#3-程序操作)
-   [🔬 项目架构](#-项目架构)
-   [🤝 贡献指南](#-贡献指南)
-   [🙏 致谢](#-致谢)
-   [📄 许可证](#-许可证)

## 🌟 主要功能

-   **🤖 全自动任务流程**：从启动差事到完成，全程无需人工干预，实现真正的“挂机”。
-   **💬 实时状态同步**：通过独立的 `Node.js` 后端，将 Bot 状态（如“面板已开”、“队伍已满”）实时发送到指定的 Steam 群聊频道。
-   **🛡️ 智能故障处理**：当 Bot 长时间无响应时，可配置通过 PushPlus 发送微信警报并退出。
-   **🚀 开箱即用**：提供合理的默认配置 (`config.yaml`)，大部分用户无需修改即可直接启动。
-   **📄 详细日志记录**：在终端中记录关键操作和潜在问题，方便排查和调试。

<!-- ## 🎬 运行演示 -->
<!-- TODO:在此处放置一张 GIF 动图来展示Bot的工作流程 -->
<!-- ![运行演示 GIF](path/to/your/demo.gif) -->

## 🔧 环境要求

-   **从源码运行**:
    -   Python >= 3.11
    -   Node.js >= v22.0
-   **运行发行版**:
    -   Windows 10 或更高版本 (无其他依赖要求)。

## 🚀 安装与运行

本项目提供两种运行方式：直接从源码运行，或使用已打包的发行版。

### 方式一：从源码运行

1.  **克隆源码**

    ```bash
    git clone https://github.com/shibeta/JNTMbot_python.git
    cd JNTMbot_python
    ```

2.  **安装 Python 依赖**

    ```bash
    pip install -r requirements.txt
    ```

3.  **安装 Node.js 依赖**

    ```bash
    cd steam_bot
    npm install --production
    cd ..
    ```

4.  **创建配置文件**
    ```bash
    mv config.yaml.example config.yaml
    ```

5.  **修改配置 (可选)**
    根据您的需求，编辑根目录下的 `config.yaml` 文件。详细说明请见 [使用说明](#1-配置文件-configyaml) 部分。

6.  **修改游戏内设置**
    修改游戏内的部分设置以适配自动化程序。详细说明请见 [使用说明](#2-游戏内设置) 部分。
7.  **启动程序**

    ```bash
    python main.py
    ```

8.  **首次登录 Steam**
    > **重要提示**：如果是第一次启动，程序会要求您在控制台中输入 Steam 用户名、密码和安全令牌码以登录 Steam Chat。成功登录后，会保存一个登录令牌 (`steam登录缓存请勿分享此文件`)，后续启动将自动登录。

### 方式二：运行发行版

1.  **下载最新发行版**
    从 [GitHub Releases](https://github.com/shibeta/JNTMbot_python/releases/latest) 或 [123 云盘](https://www.123865.com/s/05OiVv-bdsmH?pwd=bJEH) 下载最新的 `JNTMbot_python.zip` 文件。

2.  **解压文件**
    将下载的 `.zip` 文件解压到您选择的任意位置。

3.  **修改配置 (可选)**
    根据您的需求，编辑解压出的文件夹中的 `config.yaml` 文件。详细说明请见 [使用说明](#1-配置文件-configyaml) 部分。

4.  **修改游戏内设置**
    修改游戏内的部分设置以适配自动化程序。详细说明请见 [使用说明](#2-游戏内设置) 部分。
5.  **启动程序**
    双击运行 `德瑞Bot.exe`。

6.  **首次登录 Steam**
    > 同上，首次运行需要您在弹出的控制台窗口中完成 Steam 登录流程。

## 🛠️ 使用说明

### 1. 配置文件 (`config.yaml`)

大部分配置项已设置为通用值，无需修改。以下是您可能需要关注或自定义的关键配置：

-   `steamBotHost`, `steamBotPort`, `steamBotToken`

    > `steam_bot` 后端服务的相关配置。通常无需修改，除非您有特殊的网络需求或端口已被占用。

-   `steamBotProxy`

    > 访问 Steam 的 HTTP 代理。默认为 `"system"`，表示使用系统代理。如果您的网络环境特殊，可以设置成 `"http://127.0.0.1:port"` 格式的指定代理。大部分游戏加速器的“路由模式”也可以自动加速本程序。

-   `steamGroupId`

    > Bot 状态信息将发送到此 ID 的 Steam 群组。
    >
    > > **如何获取群组 ID？** 将此项改为空字符串 (`steamGroupId: ''`)，然后启动程序并登录 Steam。程序会在控制台中打印出您所在的所有群组及其 ID。复制所需 ID 并填回此处即可。

-   `steamChannelName`

    > Bot 状态信息将发送到群组中的该频道。

-   `wechatPush` 和 `pushplusToken`
    > 是否启用微信推送警报。启用后，程序连续 30 分钟未向 Steam Chat 发送信息会向微信推送警报并退出程序。
    >
    > > -   将 `wechatPush` 设为 `true` 以启用。
    > > -   启用后，必须在 `pushplusToken` 中填入您从 [PushPlus 官网](https://www.pushplus.plus) 获取的 Token。

### 2. 游戏内设置

为确保 Bot 能正常工作，请在游戏中完成以下设置：

-   ✅ 在 **手机** 购买 **事务所**。注意不是 **保镖事务所** 也不是 **办公室**。
-   ✅ 在 **事务所** 购买 **个人空间**。
-   ✅ 将 **出生点** 设置为 **事务所**。
-   ✅ 确保您的 **故事模式** 存档最后保存时为 **第一人称** 视角。
-   ✅ 已经 **完成过至少一次德瑞差事终章** (避免首次任务需要等待富兰克林电话)。
-   ✅ 确保事务所内有 **猎杀约翰尼·贡斯** 的黄色任务光圈。
-   ✴️ 可选: 降低游戏分辨率和帧率，以节省性能开销。

### 3. 程序操作

-   **首次登录**

    > 第一次运行程序时，需要手动输入 Steam 账户信息。后续将自动登录。

-   **启动时机**

    > 程序可以自动启动 GTA5。如果您在游戏运行时启动本程序，请确保您当前处于 **在线模式的仅邀请战局** 中。

-   **窗口焦点**

    > 程序运行时，**GTA5 游戏窗口必须保持为系统当前活动窗口**（即在前台）。

-   **热键控制**
    > -   暂停/恢复 Bot: **`Ctrl + F9`**
    > -   退出 Bot: **`Ctrl + F10`**

## 🔬 项目架构

-   `main.py`: 主函数，负责整合所有模块并执行核心逻辑。
-   `config.py`: 读取和初始化 `config.yaml` 中的配置。
-   `gta5_utils.py`: 封装了所有 GTA5 游戏内的自动化操作脚本。
-   `steam_utils.py`: Python 客户端，用于管理 `steam_bot` 后端并调用其 API 发送消息。
-   `ocr_engine.py`: 对 RapidOCR 的封装，用于游戏画面识别。
-   `process_utils.py`: 提供了获取进程信息、暂停进程（用于卡单）等功能。
-   `keyboard_utils.py`: 模拟键盘输入。
-   `push_utils.py`: 消息平台推送，目前实现了基于 PushPlus 的微信推送。
-   `logger.py`: 简单的日志格式化工具。
-   `steam_bot/server.js`: 基于 `node-steam-user` 的 Node.js 后端，将 Steam 功能封装为 HTTP API。
-   `steam_bot/SteamChatBot.js`: 对 `node-steam-user` 库的核心封装。
-   `gamepad_util.py` / `steam_bot/demo.js`: 未使用的文件。

## 🤝 贡献指南

我们欢迎任何形式的贡献！无论是提出问题、报告 Bug 还是提交代码。

1.  **发现 Bug?** 请通过 [GitHub Issues](https://github.com/shibeta/JNTMbot_python/issues) 提交一个详细的报告。
2.  **想要新功能?** 欢迎在 Issues 中提出您的建议。
3.  **想要贡献代码?**
    -   Fork 本仓库。
    -   创建一个新的分支 (`git checkout -b feature/AmazingFeature`)。
    -   提交您的更改 (`git commit -m 'Add some AmazingFeature'`)。
    -   将分支推送到您的 Fork (`git push origin feature/AmazingFeature`)。
    -   开启一个 Pull Request。

> **提示**: 为了规范化提交流程，后续会考虑加入 Issue 和 Pull Request 模板，以及通过 GitHub Actions 实现的 CI/CD 流程。

## 🙏 致谢

-   **傲弗拉**: 提供了德瑞 Bot 的原型设计思路。([Bilibili 空间](https://space.bilibili.com/26604157))
-   **JiNiTaiMeiBot**: [https://github.com/davidLi17/JiNiTaiMeiBot](https://github.com/davidLi17/JiNiTaiMeiBot)
-   **RapidOCR**: [https://github.com/RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR)
-   **node-steam-user**: [https://github.com/DoctorMcKay/node-steam-user](https://github.com/DoctorMcKay/node-steam-user)

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。
