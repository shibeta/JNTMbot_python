// SteamChatBot.js

const SteamUser = require("steam-user");
const fs = require("fs/promises"); // 使用 fs/promises 以便在 async/await 中使用
const readline = require("readline");
const path = require("path");

// 辅助函数，用于从控制台获取用户输入
function promptUser(query) {
    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
    });

    return new Promise((resolve) =>
        rl.question(query, (ans) => {
            rl.close();
            resolve(ans);
        })
    );
}

// 辅助函数，用于确定工作目录
function get_workdir() {
    // 在开发环境中，项目位于子文件夹中，工作目录应当为工作区目录，即上层文件夹
    // 在交付环境中，运行目录即为工作目录，但因为通过pkg打包，需要通过process.execPath获取运行目录
    const isPkg = typeof process.pkg !== "undefined";
    return isPkg ? path.dirname(process.execPath) : path.join(__dirname, "../");
}

class SteamChatBot {
    #client; // 被封装的client实体
    #loginPromise = null;
    #refreshTokenPath = path.join(get_workdir(), "steam登录缓存请勿分享此文件"); // 登录token的文件位置

    constructor(proxy = null) {
        this.#client = new SteamUser({
            // 自动重连
            autoRelogin: true,
            httpProxy: proxy,
        });

        this.#setupEventHandlers();
    }

    /**
     * 注册监听器
     */
    #setupEventHandlers() {
        this.#client.on("loggedOn", (details) => {
            console.log(
                `✅ 成功登录 SteamID : ${this.#client.steamID.getSteamID64()}`
            );
        });

        // 自动保存 refresh token
        this.#client.on("refreshToken", async (token) => {
            console.log("🔄️ 收到了新的 Refresh Token，正在保存...");
            try {
                await fs.writeFile(this.#refreshTokenPath, token);
                console.log(
                    `💾 Refresh Token 已成功保存至 ${this.#refreshTokenPath}`
                );
            } catch (err) {
                console.error("❌ 保存 Refresh Token 失败:", err);
            }
        });

        this.#client.on("disconnected", (eresult, msg) => {
            console.warn(`🔌 已从 Steam 断开连接。原因: ${msg} (${eresult})。`);
        });

        this.#client.on("error", (err) => {
            console.error("❌ 客户端遇到一个错误:", err);
        });
    }

    /**
     * 更智能的登录方法
     * 优先使用 refresh token，失败或文件不存在则回退到账户密码登录。
     * @returns {Promise<void>} 当登录成功时 resolve
     */
    async smartLogOn() {
        if (this.isLoggedIn().loggedIn) {
            console.log("Bot 已登录，无需重复操作。");
            return;
        }

        // 从文件中读入refresh token
        let token;
        try {
            token = await fs.readFile(this.#refreshTokenPath, "utf8");
        } catch (error) {
            // 只处理文件不存在的情况，其他读取错误需要注意
            if (error.code === "ENOENT") {
                console.warn(
                    "⚠️ 未找到 Refresh Token 文件，将使用账户密码登录。"
                );
                await this.logOnWithPassword();
                return;
            }
            // 如果是其他文件读取错误，则抛出
            console.error("❌ 找到 Refresh Token 文件，但读取错误！");
            throw error;
        }

        // 先验证 token 格式
        if (this.#isTokenPotentiallyValid(token)) {
            console.log("🔑 正在尝试使用 Refresh Token 登录...");
            try {
                await this.logOnWithToken(token);
                // 如果 token 登录成功，就直接返回
                return;
            } catch (error) {
                // logOnWithToken 失败 (例如 token 过期或被撤销)
                console.warn(
                    `⚠️ 使用 Refresh Token 登录失败: ${error.message}。将使用账户密码登录。`
                );
                await this.logOnWithPassword();
            }
        } else {
            console.warn(
                "⚠️ Refresh Token 文件内容无效或已损坏，将使用账户密码登录。"
            );
            await this.logOnWithPassword();
        }
    }

    /**
     * 使用 Refresh Token 登录
     * @param {string} token - Steam Refresh Token
     * @returns {Promise<void>}
     */
    logOnWithToken(token) {
        if (this.#loginPromise) return this.#loginPromise;

        this.#loginPromise = new Promise((resolve, reject) => {
            this.#client.once("loggedOn", () => {
                this.#loginPromise = null;
                resolve();
            });
            this.#client.once("error", (err) => {
                this.#loginPromise = null;
                // 让 smartLogOn 能够捕获到这个错误并回退
                reject(err);
            });
            this.#client.logOn({ refreshToken: token });
        });

        return this.#loginPromise;
    }

    /**
     * 使用账户密码登录（交互式）
     * @returns {Promise<void>}
     */
    async logOnWithPassword() {
        if (this.#loginPromise) return this.#loginPromise;

        const accountName = await promptUser("请输入 Steam 账户名: ");
        const password = await promptUser("请输入 Steam 密码: ");

        this.#loginPromise = new Promise((resolve, reject) => {
            // Steam Guard (2FA or Email)
            this.#client.once(
                "steamGuard",
                async (domain, callback, lastCodeWrong) => {
                    if (lastCodeWrong) {
                        console.warn("❌ 上一个验证码错误！");
                    }
                    const code = await promptUser(
                        `请输入发送至 ${domain || "Steam 手机应用"} 的验证码: `
                    );
                    callback(code);
                }
            );

            this.#client.once("loggedOn", () => {
                this.#loginPromise = null;
                resolve();
            });

            this.#client.once("error", (err) => {
                this.#loginPromise = null;
                reject(err);
            });

            this.#client.logOn({ accountName, password });
        });

        return this.#loginPromise;
    }

    /**
     * 检查登录状态
     * @returns {{loggedIn: boolean, accountName: string | null}}
     */
    isLoggedIn() {
        return {
            loggedIn: this.#client.steamID != null,
            accountName: this.#client.accountInfo
                ? this.#client.accountInfo.name
                : null,
        };
    }

    /**
     * 获取当前登录的用户信息
     * @returns {Promise<{name: string, steamID: string, groups: Array<{name: string, id: string}>}>}
     */
    async getCurrentUserInfo() {
        this.#ensureLoggedIn();
        const groups = await this.getGroupList();

        return {
            name: this.#client.accountInfo.name,
            steamID: this.#client.steamID.getSteamID64(),
            groups: groups,
        };
    }

    /**
     * 获取机器人所在的所有群组列表
     * @returns {Promise<Array<{name: string, id: string}>>}
     */
    async getGroupList() {
        this.#ensureLoggedIn();
        const response = await this.#client.chat.getGroups();

        return Object.values(response.chat_room_groups).map((group) => ({
            name: group.group_summary.chat_group_name,
            id: group.group_summary.chat_group_id,
        }));
    }

    /**
     * 向指定群组的指定频道发送消息
     * @param {string} groupId - 目标群组的 64 位 ID
     * @param {string} channelName - 目标频道的名称
     * @param {string} message - 要发送的消息
     * @returns {Promise<{server_timestamp: Date}>}
     * @throws {Error} 如果找不到群组或频道，或发送失败
     */
    async sendGroupMessage(groupId, channelName, message) {
        this.#ensureLoggedIn();

        const groupStateResponse =
            await this.#client.chat.setSessionActiveGroups([groupId]);

        let targetGroupState = null;
        for (const id in groupStateResponse.chat_room_groups) {
            const group = groupStateResponse.chat_room_groups[id];
            if (group.header_state.chat_group_id == groupId) {
                targetGroupState = group;
                break;
            }
        }

        if (!targetGroupState) {
            throw new Error(
                `找不到群组 ID: ${groupId}。请确认机器人是该群组成员。`
            );
        }

        const targetChannel = targetGroupState.chat_rooms.find(
            (room) => room.chat_name === channelName
        );
        if (!targetChannel) {
            throw new Error(
                `在群组 "${targetGroupState.header_state.chat_name}" 中找不到频道: "${channelName}"。`
            );
        }

        const chatId = targetChannel.chat_id;
        return this.#client.chat.sendChatMessage(groupId, chatId, message);
    }

    /**
     * 登出
     */
    logOff() {
        this.#client.logOff();
        console.log("👋 已从 Steam 登出。");
    }

    /**
     * 内部方法，确保在执行操作前已登录
     */
    #ensureLoggedIn() {
        if (!this.isLoggedIn().loggedIn) {
            throw new Error("操作失败: Bot 尚未登录。");
        }
    }

    /**
     * 内部方法，确保refresh token格式为json
     */
    #isTokenPotentiallyValid(token) {
        if (typeof token !== "string" || !token) {
            return false;
        }

        try {
            const parts = token.split(".");
            if (parts.length !== 3) {
                return false;
            }
            // 验证解码后的内容是否是有效的 JSON
            const payload = Buffer.from(parts[1], "base64url").toString("utf8");
            JSON.parse(payload);
            return true; // 如果能成功解析，说明格式是 JSON
        } catch (e) {
            return false; // 如果解码或解析失败，说明不是 JSON
        }
    }
}

module.exports = SteamChatBot;
