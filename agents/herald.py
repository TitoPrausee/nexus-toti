"""HERALD — Output & Communication Agent (Toti-derived)"""
from core.agent_base import AgentBase
from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry

class HeraldAgent(AgentBase):
    AGENT_ID = "HERALD"
    AGENT_NAME = "Herald Output Agent"
    SYSTEM_PROMPT_FILE = "herald.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry, **kwargs):
        super().__init__(llm, memory, tools, **kwargs)
