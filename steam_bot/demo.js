// 测试SteamChatBot库，推送到git仓库时记得加ignore

const SteamChatBot = require("./SteamChatBot");

// --- 配置 ---
const TARGET_GROUP_ID = "37660928"; // 替换为你的目标群组 ID
const TARGET_CHANNEL_NAME = "BOT候车室1"; // 替换为你的目标频道名称
const httpProxy = "http://127.0.0.1:7890";
// ------------

async function main() {
    const bot = new SteamChatBot((proxy = httpProxy));

    try {
        // 使用智能登录
        console.log("🚀 启动机器人并开始登录...");
        await bot.smartLogOn();

        // 验证登录状态和信息
        const status = bot.isLoggedIn();
        console.log(
            `\n🤖 Bot 存活状态: ${status.loggedIn}, 登录账户: ${status.accountName}`
        );

        if (status.loggedIn) {
            // 获取并打印当前用户信息
            const userInfo = await bot.getCurrentUserInfo();
            console.log("\n--- 当前用户信息 ---");
            console.log(`用户名: ${userInfo.name}`);
            console.log(`SteamID64: ${userInfo.steamID}`);
            console.log("所在群组:");
            userInfo.groups.forEach((g) =>
                console.log(`  - "${g.name}" (ID: ${g.id})`)
            );
            console.log("--------------------");

            // 发送一条群组消息
            console.log(
                `\n💬 准备向群组 "${TARGET_GROUP_ID}" 的频道 "${TARGET_CHANNEL_NAME}" 发送消息...`
            );
            const response = await bot.sendGroupMessage(
                TARGET_GROUP_ID,
                TARGET_CHANNEL_NAME,
                `测试bot的新的消息发送方法。发送时间: ${new Date().toLocaleTimeString()}`
            );
            console.log(
                `✅ 消息发送成功！服务器时间戳: ${response.server_timestamp}`
            );
        }
    } catch (error) {
        console.error("\n💥 在机器人主流程中发生严重错误:", error.message);
    } finally {
        // 登出 (可选, 如果你希望程序运行完后就登出)
        // 在实际的 24/7 机器人中，在用户按下ctrl+C时才需要调用这个
        // if (bot.isLoggedIn().loggedIn) {
        //     console.log("\n程序执行完毕，将在 5 秒后登出...");
        //     setTimeout(() => bot.logOff(), 5000);
        // }
    }
}

main();
