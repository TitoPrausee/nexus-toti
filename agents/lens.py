"""LENS — Analysis & Quality Control Agent (Toti-derived)"""
from core.agent_base import AgentBase
from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry

class LensAgent(AgentBase):
    AGENT_ID = "LENS"
    AGENT_NAME = "Lens Analysis Agent"
    SYSTEM_PROMPT_FILE = "lens.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry, **kwargs):
        super().__init__(llm, memory, tools, **kwargs)
