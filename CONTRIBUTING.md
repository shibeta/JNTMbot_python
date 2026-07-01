# 贡献者指南

非常感谢您对 JNTMbot 的关注！无论您是想要从源码本地运行，还是希望提交代码改进项目，本指南都将为您提供必要的帮助。

## 1. 环境要求

如需从源码运行本程序，您的开发环境需要满足以下要求：
- Windows 10 Build 18362 (即 19H1) 或更高版本
- Python >= 3.12
- Node.js >= v22.0

---

## 2. 项目架构

为了方便您快速了解代码库，以下是核心模块的简要说明：

- `main.py`: 主函数，负责整合所有模块并执行核心逻辑。
- `config.py`: 读取和初始化 `config.yaml` 中的配置。
- `RapidOCR_api.py`: 调用 `RapidOCR-json.exe` 进行 OCR 的类。
- `ocr_utils.py`: 对 RapidOCR_api 的封装，用于游戏画面识别。
- `windows_utils.py`: 封装了 Windows 中对进程和窗口的一些操作。
- `keyboard_utils.py`: 模拟键盘输入，监听键盘快捷键。
- `gamepad_utils.py`: 模拟手柄输入（依赖 ViGEmBus）。
- `push_utils.py`: 消息平台推送，目前实现了基于 PushPlus 的微信推送。
- `health_check.py`: 监控 Bot 是否正常工作。
- `app_lifecycle.py`: 通过信号量实现外部控制程序暂停和停止的工具类。
- `logger.py`: 简单的日志格式化工具。
- `gta_automator`: 封装了所有对 GTA5 的自动化操作逻辑。
- `steambot_utils.py`: 用于管理 Steam Bot 后端并调用其 API 发送消息。
- `steamgui_automation.py`: 备用方案，使用 UIAutomation 通过窗口发送 Steam 群组消息。
- `steam_bot/`: 基于 `node-steam-user` 的 Node.js 后端，将 Steam 功能封装为 HTTP API。

---

## 3. 从源码运行

> [!TIP]
> 安装依赖需要能够顺畅访问 pip 仓库和 npm 仓库。

1. **克隆源码**
   ```powershell
   git clone https://github.com/shibeta/JNTMbot_python.git
   cd JNTMbot_python
   ```

2. **安装 Python 依赖**
   ```powershell
   pip install -r requirements-dev.txt
   ```
> [!IMPORTANT]
> 安装期间可能会弹出 ViGEmBus 虚拟手柄驱动的安装程序，请接受并完成安装。

3. **安装 Node.js 依赖**
   ```powershell
   cd steam_bot
   npm install --omit=dev
   cd ..
   ```

4. **初始化配置**
   ```powershell
   cp config.yaml.example config.yaml
   ```
   如有需要，请根据 `config.yaml` 中的注释修改配置，并确保已完成 [安装与使用指南](docs/INSTALL.md) 中说明的**游戏环境设置**。

5. **启动程序**
   ```powershell
   python main.py
   ```

> [!CAUTION]
> 首次运行并在控制台登录 Steam 后，会生成 `steam登录缓存请勿分享此文件`。**该文件是未加密的长效 Steam 登录令牌，切勿提交到代码仓库或分享给他人。** 该文件已默认加入 `.gitignore`。

---

## 4. 源代码升级指南

想要同步上游最新代码，请执行：

1. **拉取最新代码并更新依赖**
   ```powershell
   git pull
   pip install -r requirements-dev.txt
   cd steam_bot
   npm install --omit=dev
   cd ..
   ```

2. **迁移配置**
   ```powershell
   # 备份旧配置
   mv config.yaml config_backup.yaml
   # 复制新模板
   cp config.yaml.example config.yaml
   # 对比差异
   diff (cat config.yaml) (cat config_backup.yaml) | findstr "=>"
   ```
   根据对比结果，将旧配置文件中的自定义值手动复制到新的 `config.yaml` 中。

---

## 5. 提交 Pull Request (PR) 流程

我们非常欢迎为项目添砖加瓦！提交流程如下：

1. Fork 本仓库。
2. 创建一个新的功能分支，例如：`git checkout -b feature/AmazingFeature` 或 `bugfix/FixSomething`。
3. 提交您的更改，建议遵循规范化的 Commit 描述：`git commit -m 'feat: Add some AmazingFeature'`。
4. 将分支推送到您的 Fork 仓库：`git push origin feature/AmazingFeature`。
5. 在 GitHub 页面开启一个 Pull Request。

> [!WARNING]
> **重要提示**：由于本项目是基于图像识别和按键模拟的游戏自动化脚本，代码逻辑高度依赖画面的微小变化和时序逻辑，**任何细微的代码变更都有可能导致意外的流程中断**。
>
> 提交 PR 时，请务必确保：
> 1. 您已经在**本地真实游戏环境**中完整跑通过了测试流程。
> 2. 如果修改了状态机或时序，请在 PR 描述中详细说明您的测试条件与覆盖场景。