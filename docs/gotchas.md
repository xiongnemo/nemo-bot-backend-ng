# Nemo-Bot-Backend-Ng 踩坑与避坑指南 (Gotchas)

本文档记录了在开发、重构 `nemo-bot-backend-ng` 过程中遇到的各种深坑。今后遇到新的奇怪问题或者机制约定，请务必更新到这里，以防后人（或 Agent）重复踩坑。

## 1. 架构与状态边界
- **配置文件 (`config.yml`) vs 数据库 (`SQLite`)**
  - **坑点描述**：刚开始重构时，容易把所有的配置（甚至包括机器人的 Prompt 偏好或频道开关）都写进 `config.yml`。
  - **避坑准则**：`config.yml` 只负责**静态基础设施**（例如：监听端口、数据库连接串、大模型 API Key、各个前端 Adapter 的 Endpoint）。所有**动态应用状态**（例如用户设置、Agent 的记忆事实、Alias 别名映射）必须存入 `store/state_store.py` (底层是 SQLite)。`config.yml` 需要重启才能生效，而 SQLite 是热更的。

## 2. 插件结构校验
- **插件加载引发 `FATAL` 退出**
  - **坑点描述**：写插件时忘记写 `_name` 或者 `_man` 属性，导致整个 Executor 在初始化 Worker 时报出 `FATAL: Plugin 'XXX' is missing required attributes`，整个系统启动失败。
  - **避坑准则**：`routing/ruleset.py` 具有严格的模块校验。所有放在 `plugins/` 目录下的合法插件，**必须**在模块顶层定义这 4 个变量：`_name` (str), `_command` (list), `_man` (str), `bot_execute` (Callable)。供 Agent 调用的还强烈建议带上 `_tool_description`。
- **自定义 LLM 参数被忽略，Agent 只收到了默认的 `query` 参数**
  - **坑点描述**：插件开发者自作主张把参数定义写成了 `_tool_parameters = {}`，导致 LLM 在调用工具时始终使用了系统兜底生成的默认 `query` 字符串参数，而不是预期的 JSON 结构（如 `code`）。
  - **避坑准则**：在 `tool_registry.py` 里，扫描插件参数的反射属性**严格绑定为 `_parameters`**。千万不要自创诸如 `_tool_parameters` 之类的变量名！

## 3. 大模型客户端 (nemollm) 的协议序列化规范
- **并发工具调用导致的 HTTP 400 错误 (INVALID_ARGUMENT)**
  - **坑点描述**：当 Agent 在一步内并发调用多个工具（如同时查询两个币价），`AgentRunner` 会把结果作为多条 `role="tool"` 的消息追加。在将这些消息发给 Gemini 或 Anthropic (Claude) API 时，如果直接一对一翻译成独立的消息结构，会被直接拒绝（400 Bad Request）。
  - **避坑准则**：
    - **OpenAI**: 原生支持多条连续的 `role: tool` 消息，可以直接发。
    - **Gemini**: 要求同回合的多个函数响应，必须合并在**单一**的 `user` 角色消息中，所有返回内容放入它的 `parts` 数组。
    - **Anthropic**: 强制要求全局历史消息严格遵循 `user -> assistant -> user` 的交替，坚决不能出现连续两个 `user`。因此连续的工具回调也必须合并在同一个 `user` 角色的 `content` 数组下，并且 type 为 `tool_result`。
  - **现状**：`nemollm/gemini_client.py` 和 `nemollm/anthropic_client.py` 已实现 Message Coalescing (消息合并) 逻辑，后续维护或接入新平台时请牢记此特性！

## 4. 热重载机制的局限性 (Core vs Plugins)
- **修改后未生效**
  - **坑点描述**：修改了 `core/`、`adapters/` 或 `config.py` 中的核心代码，但发现热重载没有触发，导致逻辑还是旧的。
  - **避坑准则**：框架的**秒级热重载只对 `plugins/` 目录下的独立插件生效**（由 `hatchling` 的 dev-mode 和 executor 的 `importlib.reload` 共同保障）。对于核心组件（Core），由于它们和主进程（Flask 监听、Scheduler 线程池、数据库池）深度绑定，热更容易导致内存泄漏或状态不一致，因此**严禁热更**。一旦修改了核心代码或配置文件，必须手动重启后端 (`Ctrl+C` -> `python app.py`)。

## 5. 全局配置引用
- **`app_config` 找不到**
  - **坑点描述**：在插件里习惯性地写 `from config import app_config`，导致 `ImportError`。
  - **避坑准则**：新版后端的全局字典叫 `backend_config`。导入姿势应该是 `from config import backend_config`。
