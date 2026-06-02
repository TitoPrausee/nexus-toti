"""FORGE — Code & Technical Implementation Agent (Toti-derived)"""
from core.agent_base import AgentBase
from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry

class ForgeAgent(AgentBase):
    AGENT_ID = "FORGE"
    AGENT_NAME = "Forge Implementation Agent"
    SYSTEM_PROMPT_FILE = "forge.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry, **kwargs):
        super().__init__(llm, memory, tools, **kwargs)
