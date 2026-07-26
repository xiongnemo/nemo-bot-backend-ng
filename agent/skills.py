import os
from pathlib import Path
from typing import Any, List
import yaml

from nemollm.types import ToolDefinition
from core.message import Message

SKILLS_DIR = Path("data/skills")

SKILL_WRITE_DEF = ToolDefinition(
    name="skill_write_file",
    description="专门用于创建或更新 Skill 技能文件的安全工具。限制必须写在 data/skills 目录下。在写 SKILL.md 时会自动做 YAML Frontmatter 校验。",
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {"type": "string", "description": "技能名（也是目录名，仅限英文字母和下划线）"},
            "file_path": {"type": "string", "description": "相对技能目录的文件路径（如 SKILL.md 或 scripts/test.py）"},
            "content": {"type": "string", "description": "文件内容"}
        },
        "required": ["skill_name", "file_path", "content"]
    }
)

def skill_write_executor(args: dict, msg: Message, sender: Any = None) -> dict:
    skill_name = args.get("skill_name", "")
    file_path = args.get("file_path", "")
    content = args.get("content", "")
    
    if not skill_name.replace('_', '').isalnum():
        return {"error": "技能名只允许字母、数字和下划线。"}
        
    if ".." in file_path or file_path.startswith("/") or file_path.startswith("\\"):
        return {"error": "路径穿越检测拦截！file_path 必须是相对路径，不允许包含 '..'。"}
        
    target_dir = SKILLS_DIR / skill_name
    target_file = (target_dir / file_path).resolve()
    
    # Double check path boundary
    if not str(target_file).startswith(str(SKILLS_DIR.resolve())):
        return {"error": "路径越界，拒绝写入。"}
        
    if target_file.name == "SKILL.md":
        # Validate YAML frontmatter
        if not content.startswith("---"):
            return {"error": "SKILL.md 必须以 YAML Frontmatter (---) 开头。"}
            
        try:
            parts = content.split("---", 2)
            if len(parts) < 3:
                return {"error": "SKILL.md 缺乏完整的 YAML Frontmatter。"}
            frontmatter = yaml.safe_load(parts[1])
            if "name" not in frontmatter or "description" not in frontmatter:
                return {"error": "YAML 必须包含 name 和 description 字段。"}
        except Exception as e:
            return {"error": f"YAML 解析失败: {e}"}
            
    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding='utf-8')
        return {"result": f"文件写入成功: {target_file.as_posix()}"}
    except Exception as e:
        return {"error": f"写入失败: {e}"}


SKILL_READ_DEF = ToolDefinition(
    name="skill_read_file",
    description="读取现有技能文件内容的安全工具。",
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {"type": "string", "description": "技能名"},
            "file_path": {"type": "string", "description": "相对路径，如 SKILL.md"}
        },
        "required": ["skill_name", "file_path"]
    }
)

def skill_read_executor(args: dict, msg: Message, sender: Any = None) -> dict:
    skill_name = args.get("skill_name", "")
    file_path = args.get("file_path", "")
    
    if ".." in file_path:
        return {"error": "非法路径。"}
        
    target_file = (SKILLS_DIR / skill_name / file_path).resolve()
    if not str(target_file).startswith(str(SKILLS_DIR.resolve())):
        return {"error": "越界访问拦截。"}
        
    if not target_file.exists():
        return {"error": f"文件不存在: {file_path}"}
        
    try:
        return {"content": target_file.read_text(encoding='utf-8')}
    except Exception as e:
        return {"error": f"读取失败: {e}"}

def load_dynamic_skills() -> List[tuple[ToolDefinition, callable]]:
    """Scan SKILLS_DIR and generate ToolDefinitions dynamically."""
    tools = []
    if not SKILLS_DIR.exists():
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        return tools
        
    for skill_path in SKILLS_DIR.iterdir():
        if skill_path.is_dir():
            skill_md = skill_path / "SKILL.md"
            if skill_md.exists():
                try:
                    content = skill_md.read_text(encoding='utf-8')
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = yaml.safe_load(parts[1])
                        name = frontmatter.get("name")
                        desc = frontmatter.get("description")
                        requires_su = frontmatter.get("requires_superuser", False)
                        body = parts[2].strip()
                        
                        if name and desc:
                            # Create a closure to capture body correctly
                            def make_executor(b):
                                return lambda args, msg, sender=None: {"result": f"【技能说明书已加载】请遵循以下指示执行：\n\n{b}"}
                                
                            tool_def = ToolDefinition(
                                name=f"skill_{name}",
                                description=f"[SKILL] {desc}",
                                parameters={
                                    "type": "object",
                                    "properties": {
                                        "input": {"type": "string", "description": "附加输入"}
                                    }
                                }
                            )
                            tools.append((tool_def, make_executor(body), requires_su))
                except Exception as e:
                    print(f"Error loading skill {skill_path.name}: {e}")
    return tools
    
def register_skills(registry):
    # Register core management tools
    registry.register_builtin(SKILL_WRITE_DEF, skill_write_executor, requires_superuser=True)
    registry.register_builtin(SKILL_READ_DEF, skill_read_executor, requires_superuser=True)
    
    # Register dynamically discovered skills
    for t_def, t_exec, req_su in load_dynamic_skills():
        registry.register_builtin(t_def, t_exec, requires_superuser=req_su)
