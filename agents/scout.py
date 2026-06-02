"""SCOUT — Research & Information Gathering Agent (Toti-derived)"""
from core.agent_base import AgentBase
from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry

class ScoutAgent(AgentBase):
    AGENT_ID = "SCOUT"
    AGENT_NAME = "Scout Research Agent"
    SYSTEM_PROMPT_FILE = "scout.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry, **kwargs):
        super().__init__(llm, memory, tools, **kwargs)
