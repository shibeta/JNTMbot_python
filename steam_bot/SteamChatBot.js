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
        var steamUserOptions = {
            autoRelogin: true,
            protocol: SteamUser.EConnectionProtocol.WebSocket,
        };
        if (proxy) {
            const proxy_lower = proxy.toLowerCase();
            if (
                proxy_lower.startsWith("http://") ||
                proxy_lower.startsWith("https://")
            ) {
                steamUserOptions.httpProxy = proxy;
            } else if (
                proxy_lower.startsWith("socks5://") ||
                proxy_lower.startsWith("socks://")
            ) {
                steamUserOptions.socksProxy = proxy;
                console.warn(
                    "⚠️ 注意：SOCKS代理无法代理域名解析，请优先使用HTTP代理。"
                );
            } else {
                console.error(
                    `❌ 不支持的代理格式或协议: "${proxy}"。请使用"http://..."或"socks5://..."等格式。`
                );
                console.warn("代理URL无效，不使用代理。");
            }
        }
        // console.log("启动参数: ")
        // for(var key in steamUserOptions) {
        //     console.log(`${key}: ${steamUserOptions[key]}`)
        // }
        this.#client = new SteamUser({ steamUserOptions });

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
        // 检查是否已有登录操作正在进行
        if (this.#loginPromise) {
            console.log("检测到已有登录操作正在进行，将等待其完成...");
            return this.#loginPromise;
        }

        if (this.isLoggedIn().loggedIn) {
            console.log("Bot 已登录，无需重复操作。");
            return;
        }

        console.log("🚀 正在启动登录流程...");
        this.#loginPromise = (async () => {
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
        })();

        try {
            await this.#loginPromise;
        } finally {
            // 无论成功或失败，完成后都必须释放锁
            this.#loginPromise = null;
        }
    }

    /**
     * 使用 Refresh Token 登录
     * @param {string} token - Steam Refresh Token
     * @returns {Promise<void>}
     */
    logOnWithToken(token) {
        return new Promise((resolve, reject) => {
            this.#client.once("loggedOn", resolve);
            this.#client.once("error", reject);
            this.#client.logOn({
                refreshToken: token,
                machineName: "steam_bot",
            });
        });
    }

    /**
     * 使用账户密码登录（交互式）
     * @returns {Promise<void>}
     */
    async logOnWithPassword() {
        while (true) {
            const accountName = await promptUser("请输入 Steam 账户名: ");
            const password = await promptUser("请输入 Steam 密码: ");

            try {
                // 将单次登录尝试封装在私有方法中
                await this._attemptPasswordLogin(accountName, password);
                // 如果 _attemptPasswordLogin 成功 resolve，说明登录成功，直接返回
                return;
            } catch (err) {
                // 分析登录失败的原因
                switch (err.eresult) {
                    case SteamUser.EResult.InvalidPassword:
                    case SteamUser.EResult.AccountNotFound:
                        console.warn(`❌ 账户名或密码错误。(${err.message})`);
                        break;

                    case SteamUser.EResult.AccountLogonDenied:
                    case SteamUser.EResult.TwoFactorCodeMismatch:
                        console.warn(
                            `❌ Steam Guard 验证码错误。(${err.message})`
                        );
                        // 这种情况通常是 _attemptPasswordLogin 内部处理了，但如果它失败了，我们在这里提示
                        break;

                    case SteamUser.EResult.RateLimitExceeded:
                        console.error(
                            "❌ 登录尝试过于频繁，您的IP可能被临时限制。请稍后再试。"
                        );
                        // 遇到速率限制，直接抛出错误，终止登录流程
                        throw err;

                    default:
                        console.error(
                            `❌ 发生未知的登录错误: ${err.message} (EResult: ${err.eresult})`
                        );
                        break; // 对于未知错误，我们也会继续重试
                }
            }
        }
    }

    /**
     * [私有] 封装单次使用账户密码登录的尝试
     * @param {string} accountName
     * @param {string} password
     * @returns {Promise<void>}
     */
    _attemptPasswordLogin(accountName, password) {
        return new Promise((resolve, reject) => {
            // 定义需要清理的监听器
            let onSteamGuard, onLoggedOn, onError;

            const cleanup = () => {
                this.#client.removeListener("steamGuard", onSteamGuard);
                this.#client.removeListener("loggedOn", onLoggedOn);
                this.#client.removeListener("error", onError);
            };

            onSteamGuard = async (domain, callback, lastCodeWrong) => {
                if (lastCodeWrong) {
                    console.warn("❌ 上一个验证码错误！请重新输入。");
                }
                const promptMessage = `请输入发送至 ${
                    domain || "Steam 手机应用"
                } 的验证码: `;
                const code = await promptUser(promptMessage);
                callback(code);
            };

            onLoggedOn = () => {
                cleanup();
                resolve();
            };

            onError = (err) => {
                cleanup();
                // 直接 reject，让 logOnWithPassword 的 catch 块来处理和分析错误
                reject(err);
            };

            // 因为用户可能输错多次验证码，这个事件会触发多次
            this.#client.on("steamGuard", onSteamGuard);
            this.#client.once("loggedOn", onLoggedOn);
            this.#client.once("error", onError);

            this.#client.logOn({
                accountName: accountName,
                password: password,
                machineName: "steam_bot",
            });
        });
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
     * 以异步非阻塞（即发即忘）的方式向指定群组的指定频道发送消息。
     * 此方法会立即返回，而消息将在后台发送。
     * @param {string} groupId - 目标群组的 64 位 ID
     * @param {string} channelName - 目标频道的名称
     * @param {string} message - 要发送的消息
     * @returns {Promise<void>} 此 Promise 在消息被提交发送后立即 resolve，不代表消息已成功送达。
     * @throws {Error} 如果在发送前找不到群组或频道，则会抛出错误。
     */
    async sendGroupMessage(groupId, channelName, message) {
        this.#ensureLoggedIn();

        let chatId;
        try {
            const groupStateResponse =
                await this.#client.chat.setSessionActiveGroups([groupId]);

            // 检查 Bot 是否在目标群组中
            let targetGroupState = null;
            if (groupStateResponse.chat_room_groups[groupId]) {
                targetGroupState = groupStateResponse.chat_room_groups[groupId];
            }

            if (!targetGroupState) {
                const errorMsg = `找不到群组 ID: ${groupId}。请确认机器人是该群组成员。`;
                console.error(`💥 ${errorMsg}`);
                throw new Error(errorMsg);
            }

            // 检查目标频道是否存在
            const targetChannel = targetGroupState.chat_rooms.find(
                (room) => room.chat_name === channelName
            );

            if (!targetChannel) {
                const errorMsg = `在群组 "${targetGroupState.header_state.chat_name}" 中找不到频道: "${channelName}"。`;
                console.error(`💥 ${errorMsg}`);
                throw new Error(errorMsg);
            }

            chatId = targetChannel.chat_id;
        } catch (error) {
            // 获取群组信息超时
            if (error.message === "Request timed out") {
                error.message =
                    "请求群组元数据超时，请检查网络连接和代理是否正常。";
            }
            console.error(
                `💥 在准备向群组 ${groupId} 发送消息时出错:`,
                error.message
            );
            throw error;
        }

        this.#client.chat
            .sendChatMessage(groupId, chatId, message)
            .then((result) => {
                console.log(
                    `✅ 消息已成功送达至群组 ${groupId} (频道: ${channelName})。`
                );
            })
            .catch((error) => {
                // 等待发送确认超时
                if (error.message === "Request timed out") {
                    console.warn(
                        `⚠️ 对群组 ${groupId} (频道: ${channelName}) 的消息发送确认超时，但消息可能已发出。`
                    );
                } else {
                    // 其他类型的错误
                    console.error(
                        `💥 发送消息到群组 ${groupId} (频道: ${channelName}) 时发生未知错误:`,
                        error
                    );
                }
            });

        // 立即返回，并告知调用者任务已提交
        console.log(
            `✅ 已提交向群组 ${groupId} (频道: ${channelName}) 发送消息的请求。`
        );
    }

    /**
     * 登出
     */
    logOff() {
        // 返回一个 Promise，以便调用者可以等待登出操作完成
        return new Promise((resolve) => {
            // 监听 'disconnected' 事件，这是登出完成的明确信号
            this.#client.once("disconnected", (eresult, msg) => {
                console.log(`👋 已从 Steam 登出。原因: ${msg} (${eresult})。`);
                resolve(); // 当断开连接时，resolve Promise
            });

            // 如果已经断开连接，则直接 resolve
            if (this.#client.steamID === null) {
                resolve();
                return;
            }

            // 发起登出请求
            this.#client.logOff();
        });
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
