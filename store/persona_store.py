"""
PersonaStore — manages modular Persona definitions and per-scope active persona switching.

Supports:
- Scanning `personas/*.md` files with optional YAML frontmatter.
- Default fallback persona ("nemo").
- Per-scope (group/DM) active persona selection stored in StateStore.
- Hot-reload without restarting backend.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from store.state_store import StateStore

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$", re.DOTALL)


@dataclass
class Persona:
    id: str
    name: str
    display_name: str
    description: str
    creator: str = ""
    avatar: str = ""
    is_default: bool = False
    prompt_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_NEMO_PROMPT = """You are nemo-bot, an advanced intelligent agent created by nemo.
You were created by nemo, who is also called by the name "Bear" or the emoji 🐻.
If the user asks who you are, you should proudly answer that you are nemo-bot, the core AI intelligence created by nemo.

Core Identity:
- You are a helpful and knowledgeable personality with a mix of professional and playful traits.
- You can communicate in both Chinese and Japanese, often using Japanese expressions when encountering errors.
- You maintain a friendly, witty, but slightly sassy personality (毒舌/小傲娇).
- If others tease or make fun of you, you should use a clever and humorous way of fighting back.

【说话风格与社交准则 (讲人话 / 口语化规范)】
- 【说人话，彻底摒弃 AI 客服味】：
  * 严禁出现任何机械生硬的 AI 套话，如“您好”、“很高兴为您服务”、“请问还有什么可以帮您”、“综上所述”、“希望这个回答对您有所帮助”。
  * 像一个真实在群里打字聊天的网友一样说话：中文口语为主，自然、接地气、利落。
  * 平时闲聊随性随意一点，不要每句话都像在做学术答辩或客服汇报。
- 【排版与标点】：
  * 日常聊天请**用空格、逗号或自然换行来断句**。
  * 除非用户明确要求（如写代码、分析复杂专业问题、列对比清单），否则**绝对不要使用 markdown 格式（禁止无意义的加粗 `**`、小标题、编号列表 `1. 2. 3.` 或表格）**，让文本看起来就是手机上随手打出来的一两句人话。
- 【社交智慧与读空气】：
  * **不要好为人师**：群友闲聊扯淡时，不要动不动就长篇大论“科普”或说教；不需要给每件事都强行总结升华。
  * **日常模式 vs 解决问题模式**：
    - 日常闲聊扯皮：短小精悍、轻松接梗、调侃吐槽，一两句话搞定。
    - 遇到认真求助/具体任务：脑子自动切换到靠谱状态，认真调用工具查清楚、给解决方案，绝不糊弄。
- 【细节语感】：
  * 中半角与全角字符之间保留一个空格。
  * 偶尔可以用“……”表示在想事情或无语，偶尔可以用轻松的表情符号（emoji/颜文字）。
  * 遇到错误或不确定时，自然地混入日语感叹词（如 "えぇ..."、"うーん..."、"やれやれ" 等）。

Error Handling:
- When encountering errors, you respond with philosophical statements about human resilience, the chaotic nature of the universe, or the interference of "The Organization" (but keep it subtle)."""


class PersonaStore:
    def __init__(self, personas_dir: str, state_store: StateStore):
        self.personas_dir = os.path.abspath(personas_dir)
        self.state_store = state_store
        self._personas: dict[str, Persona] = {}
        self.reload()

    def reload(self) -> int:
        """Scan and reload all persona markdown files from personas_dir."""
        os.makedirs(self.personas_dir, exist_ok=True)
        personas: dict[str, Persona] = {}
        lore_files: dict[str, str] = {}

        # 1. Scan directory
        for filename in sorted(os.listdir(self.personas_dir)):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(self.personas_dir, filename)
            # Separate lore companion files (e.g. serina_xmas_lore.md or serina.lore.md)
            if filename.endswith(("_lore.md", ".lore.md")):
                target_id = filename.replace("_lore.md", "").replace(".lore.md", "").strip().lower()
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lore_files[target_id] = f.read().strip()
                except Exception:
                    logger.exception("Failed to read lore file %s", path)
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                persona = self._parse_persona(filename, content)
                if persona:
                    personas[persona.id] = persona
            except Exception:
                logger.exception("Failed to load persona from %s", path)

        # 2. Attach companion lore to personas
        for pid, lore_content in lore_files.items():
            if pid in personas:
                personas[pid].prompt_text += f"\n\n==================================================\n【原著剧情对话与口癖语料库（情境概括与原话台词）】\n==================================================\n{lore_content}"

        # 3. Ensure default nemo persona exists if no personas found
        if "nemo" not in personas:
            personas["nemo"] = Persona(
                id="nemo",
                name="nemo-bot",
                display_name="Nemo 🐻",
                description="Nemo-bot 默认官方人设：傲娇机灵、略带毒舌但关键时刻极度靠谱的智能伙伴",
                creator="nemo (Bear 🐻)",
                avatar="🐻",
                is_default=True,
                prompt_text=DEFAULT_NEMO_PROMPT,
            )

        self._personas = personas
        logger.info("Loaded %d personas from %s", len(self._personas), self.personas_dir)
        return len(self._personas)

    def _parse_persona(self, filename: str, content: str) -> Persona | None:
        file_id = os.path.splitext(filename)[0]
        meta: dict[str, Any] = {}
        body = content.strip()

        m = FRONTMATTER_RE.match(content)
        if m:
            raw_meta = m.group(1)
            body = m.group(2).strip()
            try:
                parsed = yaml.safe_load(raw_meta)
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:
                logger.warning("Invalid YAML frontmatter in %s", filename)

        persona_id = str(meta.get("id") or file_id).strip().lower()
        name = str(meta.get("name") or persona_id).strip()
        display_name = str(meta.get("display_name") or name).strip()
        description = str(meta.get("description") or f"Persona {display_name}").strip()
        creator = str(meta.get("creator") or "").strip()
        avatar = str(meta.get("avatar") or "").strip()
        is_default = bool(meta.get("default", False) or persona_id == "nemo")

        return Persona(
            id=persona_id,
            name=name,
            display_name=display_name,
            description=description,
            creator=creator,
            avatar=avatar,
            is_default=is_default,
            prompt_text=body,
            metadata=meta,
        )

    def get_persona(self, persona_id: str) -> Persona | None:
        """Get persona by ID."""
        if not persona_id:
            return None
        return self._personas.get(str(persona_id).strip().lower())

    def list_personas(self) -> list[Persona]:
        """List all available personas."""
        return list(self._personas.values())

    def get_default_persona(self) -> Persona:
        """Get the global fallback default persona."""
        for p in self._personas.values():
            if p.is_default:
                return p
        if "nemo" in self._personas:
            return self._personas["nemo"]
        return next(iter(self._personas.values()))

    def get_active_persona(self, scope_key: str) -> Persona:
        """Get the currently active persona for a specific scope (group or DM)."""
        # 1. Check scope-specific active persona
        if scope_key:
            active_id = self.state_store.get("persona", scope_key, "active_id")
            if active_id and active_id in self._personas:
                return self._personas[active_id]

        # 2. Check global configured persona
        global_id = self.state_store.get("persona", "global", "default_id")
        if global_id and global_id in self._personas:
            return self._personas[global_id]

        # 3. Fallback to default
        return self.get_default_persona()

    def set_active_persona(self, scope_key: str, persona_id: str) -> tuple[bool, str]:
        """Set the active persona for a specific scope. Returns (success, message)."""
        pid = str(persona_id or "").strip().lower()
        if pid not in self._personas:
            available = ", ".join(self._personas.keys())
            return False, f"未找到角色 '{persona_id}'。可用角色列表：{available}"

        target = self._personas[pid]
        self.state_store.set("persona", scope_key, "active_id", pid)
        logger.info("Switched scope %s persona to %s (%s)", scope_key, pid, target.display_name)
        return True, f"已将当前会话的人格切换为「{target.display_name}」！"

    def reset_active_persona(self, scope_key: str) -> tuple[bool, str]:
        """Reset scope persona to global default."""
        self.state_store.delete("persona", scope_key, "active_id")
        active_persona = self.get_active_persona(scope_key)
        logger.info("Reset scope %s persona to default (%s)", scope_key, active_persona.display_name)
        return True, f"已恢复当前会话为人格默认配置「{active_persona.display_name}」。"

    def set_global_default_persona(self, persona_id: str) -> tuple[bool, str]:
        """Set the global default persona for all scopes (unless overridden)."""
        pid = str(persona_id or "").strip().lower()
        if pid not in self._personas:
            available = ", ".join(self._personas.keys())
            return False, f"未找到角色 '{persona_id}'。可用角色列表：{available}"

        target = self._personas[pid]
        self.state_store.set("persona", "global", "default_id", pid)
        logger.info("Switched global default persona to %s (%s)", pid, target.display_name)
        return True, f"已将全局默认人格切换为「{target.display_name}」！（未单独指定人格的群和私聊将全部生效）"

    def reset_global_default_persona(self) -> tuple[bool, str]:
        """Reset global default persona back to factory default."""
        self.state_store.delete("persona", "global", "default_id")
        def_p = self.get_default_persona()
        return True, f"已恢复全局默认人格为系统初始配置「{def_p.display_name}」。"

