<div align="center">

# JNTMbot - GTAOL 德瑞 BOT 自动化脚本

[![Stable](https://img.shields.io/github/v/release/shibeta/JNTMbot_python?style=for-the-badge&logo=github&color=green&label=稳定版)](https://github.com/shibeta/JNTMbot_python/releases/latest)
[![Nightly](https://img.shields.io/github/v/release/shibeta/JNTMbot_python?style=for-the-badge&logo=github&filter=nightly&color=purple&label=测试版)](https://github.com/shibeta/JNTMbot_python/releases/tag/nightly)
[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg?style=for-the-badge&logo=python)](https://www.python.org/)
[![Node.js Version](https://img.shields.io/badge/node.js-22+-green.svg?style=for-the-badge&logo=Node.js)](https://nodejs.org/)
[![License](https://img.shields.io/github/license/shibeta/JNTMbot_python?style=for-the-badge)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/shibeta/JNTMbot_python/nightly-build.yml?style=for-the-badge&logo=githubactions&label=%E6%9E%84%E5%BB%BA
)](https://github.com/shibeta/JNTMbot_python/releases/tag/nightly)

</div>

## 目录

**1.** [**关于项目**](#关于项目)  
**2.** [**环境要求**](#环境要求)  
**3.** [**安装指南**](#安装指南)  
**5.** [**交流与反馈**](#交流与反馈)  
**6.** [**致谢**](#致谢)

## 关于项目

**JNTMbot (德瑞Bot)** 是一个专为 GTA5 在线模式（增强版）设计的无人值守自动化系统，专门用于自动刷取“德瑞博士合约(数据泄露)”的最终任务“别惹德瑞”。

本程序能够在无人工干预的情况下，执行从启动差事到完成任务的完整工作流，帮助玩家在后台挂机时高效获取游戏内货币。项目基于 Python 图像识别与按键模拟，配合独立的 Node.js 后端服务，实现了高度稳定的自动化操作与状态推送。

### 关键特性

- **无人值守**：从启动差事到完成全程自动，实现真正的“零干预”挂机。
- **后台运行**：程序不占用键盘鼠标与窗口焦点，挂机时您仍可正常使用电脑进行其他工作。
- **状态推送**：通过 Steam 聊天频道实时广播 Bot 状态（如“面板已开”、“队伍已满”），也可配置微信 PushPlus 接收异常警报。
- **自动排障**：内置异常处理逻辑，自动应对黑屏警告、恶意玩家干扰、游戏崩溃等突发情况。

### 运行演示

<img width="100%" alt="运行演示.gif" src="https://github.com/user-attachments/assets/806770e6-dd41-4f54-ba80-b880977f85d4" />

## 环境要求

- 操作系统：Windows 10 Build 18362 (即 19H1) 或更高版本
- 游戏版本：GTA5 增强版 (不支持传承版)

> [!NOTE]
> 以上为直接运行发行版用户的环境要求。如果您希望从源代码编译或运行，请查阅 [贡献者指南](CONTRIBUTING.md#3-从源码运行) 。

## 安装指南

> [!IMPORTANT]
> **关于下载、安装、配置等步骤，请阅读：[安装与使用指南](docs/INSTALL.md)**

## 交流与反馈

无论您是遇到使用问题、发现了 Bug，还是想要改进代码，我们都非常欢迎您的参与！

1. **遇到使用疑问或环境配置问题？**
   请前往 [GitHub Discussions](https://github.com/shibeta/JNTMbot_python/discussions) 讨论区发帖交流。
2. **发现 Bug 或有新功能建议？**
   请通过 [GitHub Issues](https://github.com/shibeta/JNTMbot_python/issues/new/choose) 提交反馈，并附带控制台日志和游戏截图。
3. **想要参与代码贡献？**
   请阅读我们的 [贡献者指南](CONTRIBUTING.md) 了解源码运行方法、项目架构以及 PR 提交流程。

## 致谢

- **[傲弗拉](https://space.bilibili.com/26604157)**: 提供了德瑞 Bot 的原理。
- **[JiNiTaiMeiBot](https://github.com/davidLi17/JiNiTaiMeiBot)**: 本项目的原型。本项目使用 Python 重新实现了 JiNiTaiMeiBot 的大部分功能。
- **[QuellGTA](https://github.com/mageangela/QuellGTA)**: 本项目使用的差传 Bot 来源; 清理 pc_setting.bin 算法的实现。
- **[RapidOCR](https://github.com/RapidAI/RapidOCR)**: 强大而快速的 OCR 识别框架。
- **[RapidOCR-json](https://github.com/hiroi-sora/RapidOCR-json)**: RapidOCR 的一个 C++ 实现，比打包后的 Python 程序快。
- **[node-steam-user](https://github.com/DoctorMcKay/node-steam-user)**: Steam 客户端功能的 Node.js 实现。
- **[Python-UIAutomation-for-Windows](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows)**: Microsoft UI Automation 的 Python 3 封装。

## 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。
