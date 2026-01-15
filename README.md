# JNTMbot - GTAOL 德瑞差事自动化脚本

![License](https://img.shields.io/github/license/shibeta/JNTMbot_python)
![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)
![Node.js Version](https://img.shields.io/badge/node.js-22+-green.svg)

[![稳定版](https://github.com/shibeta/JNTMbot_python/actions/workflows/stable-release.yml/badge.svg)](https://github.com/shibeta/JNTMbot_python/releases/latest)
[![测试版](https://github.com/shibeta/JNTMbot_python/actions/workflows/nightly-build.yml/badge.svg)](https://github.com/shibeta/JNTMbot_python/releases/tag/nightly)

本项目是一个基于 Python 和 Node.js 的德瑞 BOT 挂机脚本。

---

## 目录

-   [🌟 主要功能](#-主要功能)
-   [🔧 环境要求](#-环境要求)
-   [🚀 安装与运行](#-安装与运行)
    -   [方式一：运行发行版](#方式一运行发行版)
    -   [方式二：从源码运行](#方式二从源码运行)
    -   [命令行参数](#命令行参数)
-   [⬆️ 升级指南](#️-升级指南)
    -   [发行版升级指南](#发行版升级指南)
    -   [源代码升级指南](#源代码升级指南)
-   [🛠️ 使用说明](#️-使用说明)
    -   [1. 配置文件 (`config.yaml`)](#1-配置文件-configyaml)
    -   [2. 游戏设置](#2-游戏设置)
    -   [3. 程序操作](#3-程序操作)
-   [🔬 项目架构](#-项目架构)
-   [🤝 贡献指南](#-贡献指南)
-   [🙏 致谢](#-致谢)
-   [📄 许可证](#-许可证)

## 🌟 主要功能

-   **🤖 全自动任务流程**：从启动差事到完成，全程无需人工干预，实现真正的“挂机”。
-   **🌙 后台挂机**：程序不占用键盘和鼠标，不占用窗口焦点，可以自由地使用电脑进行其他工作。
-   **💬 实时状态同步**：通过独立的 `Node.js` 后端，将 Bot 状态（如“面板已开”、“队伍已满”）实时发送到指定的 Steam 群聊频道。
-   **🛡️ 智能故障处理**：当 Bot 长时间无响应时，可配置通过 PushPlus 发送微信警报并退出。
-   **🚀 开箱即用**：提供合理的默认配置 (`config.yaml`)，大部分用户无需修改即可直接启动。
-   **📄 详细日志记录**：在终端中记录关键操作和潜在问题，方便排查和调试。

<!-- ## 🎬 运行演示 -->
<!-- TODO:在此处放置一张 GIF 动图来展示Bot的工作流程 -->
<!-- ![运行演示 GIF](path/to/your/demo.gif) -->

## 🔧 环境要求

-   **运行发行版**:
    -   Windows 10 Build 18362 (即 19H1) 或更高版本
    -   GTA5 增强版 (不支持传承版)
-   **从源码运行**:
    -   Windows 10 Build 18362 (即 19H1) 或更高版本
    -   GTA5 增强版 (不支持传承版)
    -   Python >= 3.12
    -   Node.js >= v22.0

## 🚀 安装与运行

本项目提供两种运行方式：使用已打包的发行版，或直接从源码运行。

### 方式一：运行发行版

1.  **下载最新发行版**

    从 [GitHub Releases](https://github.com/shibeta/JNTMbot_python/releases/latest) 或 [123 云盘](https://www.123865.com/s/05OiVv-bdsmH?pwd=bJEH) 下载最新的 `JNTMbot_python.zip` 文件。

2.  **解压文件**

    将下载的 `.zip` 文件解压到您选择的任意位置。

3.  **安装虚拟手柄驱动**

    从 [GitHub Repository](https://raw.githubusercontent.com/shibeta/JNTMbot_python/main/assets/虚拟手柄驱动ViGEmBusSetup_x64.msi) 或 [123 云盘](https://www.123865.com/s/05OiVv-bdsmH?pwd=bJEH) 下载并运行 `虚拟手柄驱动ViGEmBusSetup_x64.msi` 文件。请接受许可协议并安装该驱动以安装虚拟手柄驱动。

4.  **修改配置 (可选)**

    根据您的需求，编辑解压出的文件夹中的 `config.yaml` 文件。详细说明请见 [使用说明](#1-配置文件-configyaml) 部分。

5.  **修改游戏设置**

    修改游戏内的部分设置以适配自动化程序。详细说明请见 [使用说明](#2-游戏设置) 部分。

6.  **启动程序**

    双击运行 `德瑞Bot.exe`。

    程序支持一些可选的命令行参数，详情请查阅 [命令行参数](#命令行参数) 章节。

7.  **首次登录 Steam**

    如果是第一次启动，程序会要求您在控制台中输入 Steam 用户名、密码和安全令牌码以使用 Steam 聊天功能。成功登录后，会保存一个登录令牌 (`steam登录缓存请勿分享此文件`)，后续启动将自动登录。

    > **安全警告**：登录成功后，程序会在工作目录保存登录令牌 `steam登录缓存请勿分享此文件`。**该文件是未加密的长效 Steam 登录令牌，任何持有此文件的人都可以登录该 Steam 账号。请注意不要分享该文件。**

### 方式二：从源码运行

> **提示**：下载依赖需要能访问 pip 仓库和 npm 仓库。如果您的网络环境不佳，可以考虑使用同样基于最新源码打包的 [nightly build](https://github.com/shibeta/JNTMbot_python/releases/tag/nightly) 版本。

1.  **克隆源码**

    ```powershell
    git clone https://github.com/shibeta/JNTMbot_python.git
    cd JNTMbot_python
    ```

2.  **安装 Python 依赖**

    ```powershell
    pip install -r requirements.txt
    ```

    > 安装 Python 依赖期间，可能会弹出 [ViGEmBus 虚拟手柄驱动](https://github.com/nefarius/ViGEmBus) 的安装程序，请接受许可协议并安装该驱动以完成依赖安装。

3.  **安装 Node.js 依赖**

    ```powershell
    cd steam_bot
    npm install --omit=dev
    cd ..
    ```

4.  **初始化配置文件**

    ```powershell
    cp config.yaml.example config.yaml
    ```

5.  **修改配置 (可选)**

    根据您的需求，编辑根目录下的 `config.yaml` 文件。详细说明请见 [使用说明](#1-配置文件-configyaml) 部分。

6.  **修改游戏设置**

    修改游戏内的部分设置以适配自动化程序。详细说明请见 [使用说明](#2-游戏设置) 部分。

7.  **启动程序**

    ```powershell
    python main.py
    ```

    程序支持一些可选的命令行参数，详情请查阅 [命令行参数](#命令行参数) 章节。

8.  **首次登录 Steam**

    同上，首次运行需要您在弹出的控制台窗口中完成 Steam 登录流程。

    > **安全警告**：登录成功后，程序会在工作目录保存登录令牌 `steam登录缓存请勿分享此文件`。**该文件是未加密的长效 Steam 登录令牌，任何持有此文件的人都可以登录该 Steam 账号。请注意不要分享该文件。**

### 命令行参数

程序支持以下命令行参数，所有参数均为可选。

| 参数            | 别名 | 描述                 | 默认值        |
| :-------------- | :--- | :------------------- | :------------ |
| `--help`        | `-h` | 显示帮助信息并退出。 | (无)          |
| `--config-file` | (无) | 指定配置文件的路径。 | `config.yaml` |

## ⬆️ 升级指南

当您需要升级程序到新版本时，请参考以下指南：

### 发行版升级指南

1.  **备份 Steam 登录令牌 (可选)**

    登录令牌在程序的不同版本之间是通用的。因此，升级后可以把旧版本的 `steam登录缓存请勿分享此文件` 复制到新版本的文件夹中，这样便无需重新输入账号密码和令牌。

2.  **备份配置文件**

    新版本的配置文件中的默认值可能与旧版本不同。因此，**不建议** 直接用旧的配置文件覆盖新文件。正确的做法是：在最新的 `config.yaml` 文件基础上进行修改，将您在旧配置文件中自定义过的值逐一复制到新文件中。

    > 诚然，大多数情况下，您可以直接用旧的配置文件覆盖新文件。程序会自动向旧配置文件中添加缺少的项。
    >
    > 如果用旧的配置文件覆盖新文件后，程序无法正常工作，请改为使用最新的配置文件。

3.  **下载最新的发行版**

    详细说明请参考 [安装与运行](#方式一运行发行版) 。

4.  **迁移配置**

    -   将备份的 Steam 登录令牌放入程序文件夹。
    -   将旧配置文件中自定义过的值逐一复制到新的 `config.yaml` 中。

### 源代码升级指南

1.  **拉取最新的源代码**

    ```powershell
    cd JNTMbot_python
    git pull
    ```

2.  **更新依赖**

    ```powershell
    pip install -r requirements.txt
    cd steam_bot
    npm install --omit=dev
    cd ..
    ```

3.  **备份旧的配置文件**

    ```powershell
    mv config.yaml config_backup.yaml
    ```

4.  **初始化新的配置文件**

    ```powershell
    cp config.yaml.example config.yaml
    ```

5.  **迁移配置**

    -   对比新旧配置文件:

        ```powershell
        diff (cat config.yaml) (cat config_backup.yaml) | findstr "=>"
        ```

    -   根据对比结果，将旧配置文件中自定义过的值逐一复制到新的 `config.yaml` 中。

## 🛠️ 使用说明

### 1. 配置文件 (`config.yaml`)

大部分配置项已设置为通用值，无需修改。以下是您可能需要关注或自定义的关键配置：

-   `steamBotHost`, `steamBotPort`, `steamBotToken`

    > `steam_bot` 后端服务的相关配置。通常无需修改，除非您有特殊的网络需求或端口已被占用。

-   `steamBotProxy`

    > `steam_bot` 后端服务访问 Steam 的代理。默认为 `"system"`，表示使用系统代理。也可以配置为使用 HTTP 代理或 SOCKS 代理。

-   `steamGroupId` 和 `steamChannelName`

    > 通过 `steam_bot` 发送消息时，将发送到该 ID 的 Steam 群组中的该频道。
    >
    > > **如何获取群组 ID？** 将此项改为空字符串 (`steamGroupId: ''`)，然后启动程序并登录 Steam。程序会在控制台中打印出您所在的所有群组及其 ID。复制所需 ID 并填回此处即可。

-   `useAlterMessagingMethod` 和 `AlterMessagingMethodWindowTitle`

    > 是否使用备用的 Steam 消息发送方式。启用后，将禁用 `steam_bot` 服务，改为通过 Steam GUI 发送消息。
    >
    > > -   将 `useAlterMessagingMethod` 设置为 `true` 以启用。
    > > -   启用后，必须**手动打开对应的 Steam 群组的聊天窗口，并切换至对应的频道**。
    > > -   启用后，必须在 `AlterMessagingMethodWindowTitle` 填入对应聊天窗口的窗口标题。不需要完整的标题，只要能唯一搜索到该窗口即可。

-   `enableWechatPush` 和 `pushplusToken`
    > 是否启用微信推送警报。启用后，当程序运行一段时间后发生报错退出，或健康状态发生变化时，会向微信推送错误信息。
    >
    > > -   将 `enableWechatPush` 设为 `true` 以启用。
    > > -   启用后，必须在 `pushplusToken` 中填入您从 [PushPlus 官网](https://www.pushplus.plus) 获取的 Token。
    > > -   必须将 `enableHealthCheck` 设为 `true`，才会在健康状态发生变化时推送。

### 2. 游戏设置

为确保 Bot 能正常工作，请在游戏中完成以下设置：

-   ✅ 确保游戏版本为**增强版**，并且游戏内语言设置为**简体中文**。
-   ✅ 确保**没有**连接**任何游戏手柄**到电脑 (会和虚拟手柄冲突)。
-   ✅ 在 **手机** 购买 **事务所**。注意不是 **保镖事务所** 也不是 **办公室**。
-   ✅ 在 **事务所** 购买 **个人空间**。
-   ✅ 将 **出生点** 设置为 **事务所**。
-   ✅ 确保您的 **故事模式** 存档最后保存时为 **第一人称** 视角。
-   ✅ 已经 **完成过至少一次德瑞差事终章** (避免首次任务需要等待富兰克林电话)。
-   ✅ 确保事务所内有 **猎杀约翰尼·贡斯** 的黄色任务光圈。
-   ✴️ 可选: 降低游戏分辨率和最大帧率，以节省性能开销。
-   ✴️ 可选: 在 Steam 游戏设置中 **关闭 Steam 游戏内叠加** ，以避免遮挡游戏窗口。

最后，请关闭游戏，或者进入 **在线模式的仅邀请战局** 。

### 3. 控制热键

程序启动后，支持使用键盘热键来控制程序：

-   暂停/恢复 Bot: **`Ctrl + F9`**
-   退出程序: **`Ctrl + F10`**

## 🔬 项目架构

-   `main.py`: 主函数，负责整合所有模块并执行核心逻辑。
-   `config.py`: 读取和初始化 `config.yaml` 中的配置。
-   `RapidOCR_api.py`: 调用`RapidOCR-json.exe`进行 OCR 的类。[来源](https://github.com/hiroi-sora/RapidOCR-json/raw/refs/heads/main/api/python/RapidOCR_api.py)
-   `ocr_utils.py`: 对 RapidOCR_api 的封装，用于游戏画面识别。
-   `windows_utils.py`: 封装了 Windows 中对进程和窗口的一些操作。
-   `keyboard_utils.py`: 模拟键盘输入，监听键盘快捷键。
-   `gamepad_utils.py`: 模拟手柄输入。
-   `push_utils.py`: 消息平台推送，目前实现了基于 PushPlus 的微信推送。
-   `health_check.py`: 监控 Bot 是否正常工作。
-   `logger.py`: 简单的日志格式化工具。
-   `gta_automator`: 封装了所有对 GTA5 的自动化操作。
-   `steambot_utils.py`: 用于管理 `steam_bot` 后端并调用其 API 发送消息。
-   `steamgui_automation.py`: 使用 UIAutomation 通过窗口发送 Steam 群组消息。
-   `steam_bot`: 基于 `node-steam-user` 的 Node.js 后端，将 Steam 功能封装为 HTTP API。

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

-   **[傲弗拉](https://space.bilibili.com/26604157)**: 提供了德瑞 Bot 的原理。
-   **[JiNiTaiMeiBot](https://github.com/davidLi17/JiNiTaiMeiBot)**: 本项目的原型。本项目使用 Python 重新实现了 JiNiTaiMeiBot 的大部分功能。
-   **[QuellGTA](https://github.com/mageangela/QuellGTA)**: 本项目使用的差传 Bot 来源; 清理 pc_setting.bin 算法的实现。
-   **[RapidOCR](https://github.com/RapidAI/RapidOCR)**: 强大而快速的 OCR 识别框架。
-   **[RapidOCR-json](https://github.com/hiroi-sora/RapidOCR-json)**: RapidOCR 的一个 C++ 实现，比打包后的 Python 程序快。
-   **[node-steam-user](https://github.com/DoctorMcKay/node-steam-user)**: Steam 客户端功能的 Node.js 实现。
-   **[Python-UIAutomation-for-Windows](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows)**: Microsoft UI Automation 的 Python 3 封装。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。
