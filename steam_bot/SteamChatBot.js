const SteamUser = require("steam-user");
const fs = require("fs/promises"); // 使用 fs/promises 以便在 async/await 中使用
const prompts = require("prompts");
const path = require("path");

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
            webCompatibilityMode: true,
        };
        if (proxy) {
            const proxy_lower = proxy.toLowerCase();
            if (
                proxy_lower.startsWith("http://") ||
                proxy_lower.startsWith("https://")
            ) {
                // HTTP 代理
                steamUserOptions.httpProxy = proxy;
            } else if (
                proxy_lower.startsWith("socks4a://") ||
                proxy_lower.startsWith("socks5h://")
            ) {
                // 支持域名解析的 SOCKS 代理
                steamUserOptions.socksProxy = proxy;
            } else if (
                proxy_lower.startsWith("socks4://") ||
                proxy_lower.startsWith("socks5://")
            ) {
                // 不支持域名解析的 SOCKS 代理
                steamUserOptions.socksProxy = proxy;
                console.warn(
                    "⚠️ 注意：当前代理协议无法代理域名解析，易受DNS污染影响。请优先使用HTTP代理或SOCKS4A，SOCKS5H代理。"
                );
            } else if (proxy_lower.startsWith("socks://")) {
                // socks-proxy-agent 会将 socks:// 视为 socks5h://
                steamUserOptions.socksProxy = proxy;
                console.warn(
                    "⚠️ 注意：未指明SOCKS代理协议版本，将视为支持域名解析的SOCKS5H代理。"
                );
            } else {
                console.error(
                    '❌ 不支持的代理格式或协议: "%s"。请使用"http://..."或"socks://..."等格式。',
                    proxy
                );
                console.warn("代理URL无效，不使用代理。");
            }
        }
        // console.log("启动参数: ");
        // for (var key in steamUserOptions) {
        //     console.log(`${key}: ${steamUserOptions[key]}`);
        // }
        this.#client = new SteamUser(steamUserOptions);

        this.#setupEventHandlers();
    }

    /**
     * 注册监听器
     */
    #setupEventHandlers() {
        this.#client.on("loggedOn", (details) => {
            console.log(
                "✅ 成功登录 SteamID : %s",
                this.#client.steamID.getSteamID64()
            );
        });

        // 自动保存 refresh token
        this.#client.on("refreshToken", async (token) => {
            console.log("🔄️ 收到了新的 Refresh Token，正在保存...");
            try {
                await fs.writeFile(this.#refreshTokenPath, token);
                console.log(
                    "💾 Refresh Token 已成功保存至 %s",
                    this.#refreshTokenPath
                );
            } catch (err) {
                console.error("❌ 保存 Refresh Token 失败:", err.message);
            }
        });

        this.#client.on("disconnected", (eresult, msg) => {
            console.warn(
                "🔌 已从 Steam 断开连接。原因: %s (%s)。",
                msg,
                eresult
            );
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
                        "⚠️ 使用 Refresh Token 登录失败: %s。将使用账户密码登录。",
                        error.message
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
            this.#loginPromise;
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
            const response = await prompts(
                [
                    {
                        type: "text",
                        name: "username",
                        message: "请输入 Steam 账户名:",
                    },
                    {
                        type: "password",
                        name: "password",
                        message: "请输入 Steam 密码:",
                    },
                ],
                {
                    // 处理用户按 Ctrl+C 取消的情况
                    onCancel: () => process.exit(1),
                }
            );
            const accountName = response.username;
            const password = response.password;

            // 简单的校验，防止空输入导致无效请求
            if (!accountName || !password) {
                console.log("❌ 账户名或密码不能为空，请重新输入。");
                continue;
            }

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
                        console.warn("❌ 账户名或密码错误。(%s)", err.message);
                        break;

                    case SteamUser.EResult.AccountLogonDenied:
                    case SteamUser.EResult.TwoFactorCodeMismatch:
                        console.warn(
                            "❌ Steam Guard 验证码错误。(%s)",
                            err.message
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
                            "❌ 发生未知的登录错误: %s (EResult: %s)",
                            err.message,
                            err.eresult
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
                const steamGuardClient = domain
                    ? String(domain)
                    : "Steam 手机应用";
                const response = await prompts(
                    [
                        {
                            type: "text",
                            name: "code",
                            message: `请输入发送至 ${steamGuardClient} 的验证码: `,
                        },
                    ],
                    {
                        // 处理用户按 Ctrl+C 取消的情况
                        onCancel: () => process.exit(1),
                    }
                );
                const code = response.code;
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
     * [私有] 获取群组状态数据
     * 负责处理网络请求、超时判断以及验证 Bot 是否在群组中。
     * @param {string} groupId
     * @returns {Promise<SteamUser.SteamChatRoomClient.ChatRoomGroupState>} 返回群组的详细状态对象 (包含 chat_rooms 等)
     */
    async #fetchGroupState(groupId) {
        let groupStateResponse;
        try {
            // 发起网络请求
            groupStateResponse = await this.#client.chat.setSessionActiveGroups(
                [groupId]
            );
        } catch (error) {
            if (error.message === "Request timed out") {
                throw new Error("请求群组元数据超时，请检查网络连接。");
            }
            throw error;
        }

        // 检查返回数据中是否包含目标群组
        const targetGroupState = groupStateResponse.chat_room_groups[groupId];

        if (!targetGroupState) {
            throw new Error(
                `找不到群组 ID: ${groupId}。请确认机器人是该群组成员。`
            );
        }

        return targetGroupState;
    }

    /**
     * 获取指定群组的所有频道列表
     * @param {string} groupId
     * @returns {Promise<Array<{name: string, id: string, isVoiceChannel: bool}>>} 数组<{频道名称, ID, 是否为语音频道}>
     */
    async getGroupChannels(groupId) {
        this.#ensureLoggedIn();

        // 获取群组状态
        const groupState = await this.#fetchGroupState(groupId);

        // 获取频道列表
        return groupState.chat_rooms.map((room) => ({
            name: room.chat_name,
            id: String(room.chat_id),
            isVoiceChannel: room.voice_allowed,
        }));
    }

    /**
     * 以异步非阻塞（即发即忘）的方式向指定群组的指定频道发送消息。
     * @param {string} groupId - 目标群组的 ID
     * @param {string} channelId - 目标频道的 ID
     * @param {string} message - 要发送的消息
     * @returns {Promise<void>}
     */
    async sendGroupMessage(groupId, channelId, message) {
        this.#ensureLoggedIn();

        try {
            // 激活群组会话
            const groupState = await this.#fetchGroupState(groupId);

            // 验证频道 ID 是否存在于该群组中
            const targetChannel = groupState.chat_rooms.find(
                (room) => String(room.chat_id) === String(channelId)
            );

            if (!targetChannel) {
                throw new Error(
                    `在群组 "${String(
                        groupState.header_state.chat_name
                    )}" 中找不到 ID 为 "${channelId}" 的频道。`
                );
            }
        } catch (error) {
            console.error(
                "💥 在准备向群组 %s 发送消息时出错:",
                groupId,
                error.message
            );
            throw error; // 抛出错误，终止发送
        }

        // 发送消息
        this.#client.chat
            .sendChatMessage(groupId, channelId, message)
            .then((result) => {
                console.log(
                    "✅ 消息已成功送达至群组 %s (频道ID: %s)。",
                    groupId,
                    channelId
                );
            })
            .catch((error) => {
                if (error.message === "Request timed out") {
                    console.warn(
                        "⚠️ 对群组 %s (频道ID: %s) 的消息发送确认超时，但消息可能已发出。",
                        groupId,
                        channelId
                    );
                } else {
                    console.error(
                        "💥 发送消息到群组 %s (频道ID: %s) 时发生错误:",
                        groupId,
                        channelId,
                        error
                    );
                }
            });

        console.log(
            "✅ 已提交向群组 %s (频道ID: %s) 发送消息的请求。",
            groupId,
            channelId
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
                console.log(
                    "👋 已从 Steam 登出。原因: %s (%s)。",
                    msg,
                    eresult
                );
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
