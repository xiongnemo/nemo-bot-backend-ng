# Agent Skills 架构与工作流

Agent Skills 系统是 `nemo-bot-backend-ng` 为大模型赋能的核心可扩展机制。与传统的 Python 硬编码 Plugin 不同，Skill 是一种基于自然语言（Markdown）构建的轻量级“标准操作程序 (SOP)”，能够零成本热加载。

## 1. 核心设计理念

1. **逻辑与工具分离**：
   - 底层 Python 工具（如 `webfetch`、`admin_shell`、`skill_write_file`）只提供原子级的操作能力。
   - Skill 则通过 Markdown 中的 `Instructions`，教导大模型如何组合使用这些底层工具来完成复杂的业务流（Workflow）。
2. **按需展开 (Lazy Loading)**：
   - 为了节省上下文 Token 并防止模型注意力涣散，在初始状态下，大模型只会看到所有技能的 `name` 和 `description`。
   - 只有当大模型主动调用某个 Skill（触发对应的 Tool）时，系统才会读取并返回该技能的完整说明书。
3. **零成本热加载**：
   - 技能以文件夹形式存在于 `data/skills/` 中。每次大模型请求前，系统会动态扫描该目录以生成 Tool 列表。
   - 创建或修改技能后无需重启 Bot，下一轮对话立刻生效。

## 2. 目录规范

每个技能必须是一个独立的文件夹。例如创建一个叫 `analyze_stock` 的技能：
```text
data/skills/analyze_stock/
├── SKILL.md       (必填：核心元数据与自然语言指令)
├── scripts/       (可选：专供该技能调用的辅助脚本，如 Python 或 Shell)
├── resources/     (可选：静态参考资料或模板)
└── examples/      (可选：使用示例)
```

## 3. SKILL.md 格式

`SKILL.md` 必须以 YAML Frontmatter 开头，紧跟 Markdown 格式的执行指示。

```markdown
---
name: analyze_stock
description: 获取并分析最新的股票数据。
requires_superuser: false  # (可选) 设置为 true 则仅超级管理员可调用
---
# Instructions
1. 首先，调用 `crypto_trend` 或相应的查询工具获取股价。
2. 然后，运行当前目录下 `scripts/format.py` 来处理数据。
3. 最后，将结果以表格形式发送给用户。
```

## 4. 权限与安全机制

由于 Skill 系统赋予了大模型极高的自动化能力，因此设计了双重防线来保障系统安全，**特别是严格限制非 Superuser 的写权限**。

### 4.1 安全文件读写底座 (`skill_manager.py`)
为了避免大模型使用 `admin_shell` 直接向磁盘写入文件（可能引发路径穿越漏洞），系统提供了原生的 `skill_write_file` 和 `skill_read_file` 工具。
- **物理沙盒隔离**：强制校验所有路径必须位于 `data/skills/` 目录下，遇到任何类似 `../` 的越界尝试直接拦截。
- **强制格式检查**：当写入 `SKILL.md` 时，底层通过 Python 验证 YAML 格式的合法性，防止生成损坏的技能。
- **特权专享**：在 Registry 注册时，`skill_write_file` 和 `skill_read_file` 被严格标记为 `requires_superuser=True`。普通用户在与 Agent 对话时，甚至不知道这些工具的存在。

### 4.2 特权技能隔离
如果你编写了一个涉及删改系统配置或执行危险脚本的技能，只需在 YAML 中声明 `requires_superuser: true`，该技能在普通用户的会话中将被完全屏蔽。

### 4.3 远程安装阻断机制 (`install_skill`)
当通过元技能 `install_skill` 从外部拉取第三方技能包时：
- **纯净模式**：只有纯 Markdown 的技能包被允许静默安装。
- **高危阻断**：一旦发现 `.py`, `.sh`, `.exe` 等任何可执行文件，大模型会停止写入并立刻向用户发出警告。必须在下一轮对话中获得用户的明确批准后，才会放行并使用沙盒写入工具落盘。
