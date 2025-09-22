const express = require("express");
const SteamChatBot = require("./SteamChatBot.js");

// 解析启动参数
// 设置代理
const proxyArg = process.argv.find((arg) => arg.startsWith("--proxy="));
const proxy = proxyArg ? proxyArg.split("=")[1] : null;

if (proxy) {
    console.log(`🚀 使用代理服务器: ${proxy}`);
} else {
    console.log("🚀 未指定代理服务器。");
}
// 设置监听地址
const hostArg = process.argv.find((arg) => arg.startsWith("--host="));
const HOST = hostArg ? hostArg.split("=")[1] : "127.0.0.1";
// 设置监听端口
const portArg = process.argv.find((arg) => arg.startsWith("--port="));
const PORT = portArg ? portArg.split("=")[1] : 13091;
// 设置访问令牌
const tokenArg = process.argv.find((arg) => arg.startsWith("--auth_token="));
const AUTH_TOKEN = tokenArg ? tokenArg.split("=")[1] : "0x4445414442454546";

// 初始化Steam Bot
console.log("🤖 正在初始化 Steam Bot...");
const bot = new SteamChatBot(proxy);
console.log("🤖 Steam Bot 初始化完成。");

// --- HTTP 服务器设置 ---
const app = express();
app.use(express.json()); // 用于解析JSON格式的请求体

// 简单的Token身份验证中间件
const authenticateToken = (req, res, next) => {
    const authHeader = req.headers["authorization"];
    const token = authHeader && authHeader.split(" ")[1]; // Bearer TOKEN

    if (token == null) {
        return res.status(401).json({ error: "未提供认证 Token。" });
    }
    if (token !== AUTH_TOKEN) {
        return res.status(403).json({ error: "无效的认证 Token。" });
    }
    next();
};

// 应用身份验证中间件到所有需要保护的路由
app.use(authenticateToken);

// --- API 路由 ---

/**
 * 返回后端状态
 */
app.get("/health", (req, res) => {
    res.sendStatus(200);
});

/**
 * 返回登录状态
 */
app.get("/status", (req, res) => {
    const status = bot.isLoggedIn();
    if (status.loggedIn) {
        res.status(200).json({
            name: status.accountName || "N/A",
        });
    } else {
        res.status(401).json({
            error: "操作失败: Bot 尚未登录。",
        });
    }
});

/**
 * 触发机器人登录
 */
app.post("/login", async (req, res) => {
    if (bot.isLoggedIn().loggedIn) {
        return res
            .status(200)
            .json({ success: true, message: "Bot 已处于登录状态。" });
    }

    try {
        console.log("⚙️ 收到 API 请求，正在触发登录流程...");
        await bot.smartLogOn();
        res.status(200).json({
            success: true,
            message: "登录流程已成功触发并完成。",
        });
    } catch (error) {
        console.error("💥 API 触发的登录失败:", error);
        res.status(500).json({
            error: "登录过程中发生错误。",
            details: error.message,
        });
    }
});

/**
 * 返回用户信息
 */
app.get("/userinfo", async (req, res) => {
    if (!bot.isLoggedIn().loggedIn) {
        return res.status(401).json({ error: "操作失败: Bot 尚未登录。" });
    }

    try {
        const userInfo = await bot.getCurrentUserInfo();
        res.status(200).json(userInfo);
    } catch (error) {
        res.status(500).json({
            error: "获取用户信息时发生内部错误。",
            details: error.message,
        });
    }
});

/**
 * 发送消息到群组
 */
app.post("/send-message", async (req, res) => {
    if (!bot.isLoggedIn().loggedIn) {
        return res.status(401).json({ error: "操作失败: Bot尚未登录。" });
    }

    console.log("原始请求体 (解析后):", req.body);
    const { groupId, channelName, message } = req.body;

    // 参数校验
    if (!groupId || !channelName || !message) {
        return res.status(400).json({
            error: "请求体无效，必须包含 'groupId', 'channelName', 和 'message'。",
        });
    }

    try {
        console.log(
            `💬 收到API请求: 向群组[${groupId}]的频道[${channelName}]发送消息...`
        );
        const result = await bot.sendGroupMessage(
            groupId,
            channelName,
            message
        );
        console.debug(
            `🧑‍💻 后端已完成发送消息操作。`
        );
        res.status(200).json({
            success: true,
            message: "消息已成功发送。",
            ...result,
        });
    } catch (error) {
        // 根据错误类型返回具体的状态码
        if (error.message.includes("发送操作超时")) {
            res.status(202).json({
                error: "服务器确认超时，但消息有可能已成功发送。",
                details: error.message,
            });
        } else if (error.message.includes("找不到群组")) {
            res.status(400).json({
                error: "发送失败：找不到指定的群组。",
                details: error.message,
            });
        } else if (error.message.includes("找不到频道")) {
            res.status(400).json({
                error: "发送失败：找不到指定的频道。",
                details: error.message,
            });
        } else {
            res.status(500).json({
                error: "发送消息时发生内部错误。",
                details: error.message,
            });
        }
    }
});

/**
 * 登出 Steam
 */
app.post("/logout", async (req, res) => {
    try {
        const status = bot.isLoggedIn();

        if (status.loggedIn) {
            console.log("👋 收到 API 登出请求，正在从 Steam 登出...");

            await bot.logOff();

            console.log("✅ 已成功从 Steam 登出。");
            res.status(200).json({
                success: true,
                message: "已成功从 Steam 登出。",
            });
        } else {
            console.log("👋 收到 API 登出请求，但 Bot 本身未登录。");
            res.status(200).json({
                success: true,
                message: "Bot 当前未登录，无需执行登出操作。",
            });
        }
    } catch (error) {
        console.error("💥 在登出过程中发生错误:", error);
        res.status(500).json({
            success: false,
            message: "登出过程中发生内部错误。",
            details: error.message,
        });
    }
});

// 启动服务器
const server = app.listen(PORT, HOST, () => {
    console.log(`\n✅ HTTP 后端已启动，监听于 http://${HOST}:${PORT}`);
    console.log(
        `🔑 请在请求的 Authorization Header 中使用 Bearer Token: ${AUTH_TOKEN}`
    );
    console.log("\n--- 可用API端点 ---");
    console.log(`GET  /health       - 获取后端状态`);
    console.log(`GET  /status       - 获取登录状态`);
    console.log(`POST /login        - (重新)触发登录流程`);
    console.log(`GET  /userinfo     - 获取当前登录的用户信息`);
    console.log(`POST /send-message - 发送群组消息`);
    console.log(`POST /logout       - 从 Steam 登出`);
    console.log("-------------------\n");
});

// 响应 Ctrl+C 退出程序
process.on("SIGINT", () => {
    console.log("\n收到 SIGINT (Ctrl+C).");
    if (bot.isLoggedIn().loggedIn) {
        console.log("正在登出 Steam...");
        bot.logOff();
    }
    server.close(() => {
        console.log("HTTP 服务器已关闭。");
        process.exit(0);
    });
});

// 开始登录流程
bot.smartLogOn().catch((err) => {
    // 初始登录失败时记录错误，服务器仍会启动，但大部分接口会返回“未登录”
    console.error(
        `💥 初始登录尝试失败: ${err.message}。服务器将继续运行，请通过 API 检查状态。`
    );
});
