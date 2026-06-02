"""
NEXUS Self-Reflection & ReAct Loop Engine
============================================
Hermes-inspired self-evaluation, ReAct (Reason+Act) loop, and planning.

Features:
  - Self-reflection on LLM output quality
  - ReAct loop: Thought → Action → Observation → Final Answer
  - Self-correction for code with error feedback
  - Step-by-step planning with agent/tool assignment
  - Plan evaluation and optimization

Uses LLMClient from core.llm_client with agent_id="NEXUS-0".
"""

import json
import re
import logging
import time
from typing import Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# SAFE IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    from core.llm_client import LLMClient, Message, LLMResponse
except ImportError:
    try:
        from .llm_client import LLMClient, Message, LLMResponse
    except ImportError:
        LLMClient = None
        Message = None
        LLMResponse = None

try:
    from core.tools import ToolRegistry
except ImportError:
    try:
        from .tools import ToolRegistry
    except ImportError:
        ToolRegistry = None


# ═══════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════

AGENT_ID = "NEXUS-0"

REFLECTION_SYSTEM_PROMPT = """\
You are a critical self-reflection engine for the NEXUS agent system.
Your job is to evaluate the quality of an LLM's output against a given task.

Evaluate the result on these dimensions:
1. **Completeness** — Does the result fully address the task?
2. **Correctness** — Is the information/logic accurate?
3. **Clarity** — Is the result well-structured and understandable?
4. **Actionability** — Can the result be directly used or does it need more work?

Return your evaluation as a JSON object with this exact structure:
{
  "quality_score": 0.0-1.0,
  "issues": ["list of specific issues found"],
  "improvements": ["list of suggested improvements"],
  "should_retry": true/false
}

Rules:
- quality_score: 0.0 = completely wrong/irrelevant, 1.0 = perfect
- should_retry: true if quality_score < 0.6 or there are critical issues
- Be honest and specific — no vague feedback
- If the result is good enough, set should_retry to false
- Always return valid JSON, nothing else
"""

REACT_SYSTEM_PROMPT = """\
You are a ReAct (Reason+Act) reasoning engine in the NEXUS agent system.

You solve tasks step by step using this format:

THOUGHT: <your reasoning about what to do next>
ACTION: <tool_name>(<json arguments>)
OBSERVATION: <will be provided after action execution>

... repeat Thought/Action/Observation as needed ...

When you have enough information to give a final answer:

FINAL_ANSWER: <your complete answer>

Available tools:
{tool_descriptions}

Rules:
- Always start with THOUGHT before taking any action
- Use ACTION to call tools — format: tool_name({"key": "value"})
- After each action, you will receive an OBSERVATION
- You may use multiple Thought/Action/Observation cycles
- When confident, provide FINAL_ANSWER
- Never output anything outside the THOUGHT/ACTION/OBSERVATION/FINAL_ANSWER format
- Keep THOUGHTs concise and focused
- If a tool fails, try a different approach in the next THOUGHT
"""

SELF_CORRECT_SYSTEM_PROMPT = """\
You are a self-correction engine for the NEXUS agent system.
Given code that produced an error, produce a corrected version.

Rules:
1. Analyze the error message carefully
2. Identify the root cause
3. Fix the specific issue — don't rewrite everything
4. Preserve the original intent and structure
5. Return ONLY the corrected code, no explanations or markdown fences
6. If the error is in imports, fix imports
7. If the error is a TypeError/ValueError/NameError, fix the specific line
8. If the error is a logic error, correct the logic minimally
"""

PLAN_SYSTEM_PROMPT = """\
You are a planning engine for the NEXUS agent system.
Create a step-by-step plan to accomplish the given task.

Available agents: {agents}
Available tools: {tools}

Return the plan as a JSON array of step objects:
[
  {{
    "step": 1,
    "action": "description of what to do",
    "agent": "agent name to handle this step",
    "tool": "tool to use (if applicable)",
    "depends_on": []
  }},
  ...
]

Rules:
- Each step should be atomic and clear
- depends_on lists step numbers that must complete first
- Agent should be one of: {agents}
- Tool should be one of: {tools}
- Steps can run in parallel if they have no dependencies
- Return ONLY valid JSON, no other text
"""

PLAN_EVALUATE_SYSTEM_PROMPT = """\
You are a plan evaluation engine for the NEXUS agent system.
Evaluate the given plan for quality and suggest optimizations.

Evaluate on:
1. Completeness — Does the plan cover all aspects of the task?
2. Ordering — Are dependencies correct and minimal?
3. Efficiency — Can any steps be parallelized or merged?
4. Feasibility — Are the chosen agents and tools appropriate?

Return a JSON object:
{
  "score": 0.0-1.0,
  "issues": ["list of issues"],
  "optimized_plan": [optimized step objects with same structure]
}

Return ONLY valid JSON.
"""


# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════

@dataclass
class ReflectionResult:
    """Result of a self-reflection evaluation."""
    quality_score: float
    issues: list[str]
    improvements: list[str]
    should_retry: bool
    raw_response: str = ""


@dataclass
class ReActStep:
    """A single step in the ReAct loop."""
    step_number: int
    thought: str = ""
    action: str = ""
    action_args: dict = field(default_factory=dict)
    observation: str = ""
    timestamp: float = 0.0


@dataclass
class ReActResult:
    """Result of a complete ReAct loop execution."""
    task: str
    steps: list[ReActStep]
    final_answer: str
    total_steps: int
    success: bool
    elapsed: float = 0.0


# ═══════════════════════════════════════════════════════════
# REFLECTION ENGINE
# ═══════════════════════════════════════════════════════════

class ReflectionEngine:
    """
    Self-reflection and ReAct loop engine for the NEXUS system.

    Uses LLMClient with agent_id="NEXUS-0" for all LLM calls.

    Usage:
        llm = LLMClient()
        engine = ReflectionEngine(llm_client=llm)

        # Self-reflection
        result = engine.reflect("Write a function", "def foo(): pass")

        # ReAct loop
        result = engine.react_loop("Find Python version", tools=registry)

        # Self-correction
        corrected = engine.self_correct("Sort list", code, error_msg)
    """

    def __init__(self, llm_client: Any, max_iterations: int = 5):
        """
        Initialize the ReflectionEngine.

        Args:
            llm_client: An LLMClient instance for making LLM calls.
            max_iterations: Maximum ReAct loop iterations.
        """
        if LLMClient is not None and not isinstance(llm_client, LLMClient):
            logger.warning(
                f"llm_client is not an LLMClient instance (got {type(llm_client).__name__}). "
                "Proceeding anyway — ensure it has a .chat() method."
            )

        self.llm_client = llm_client
        self.max_iterations = max_iterations

    # ─── SELF-REFLECTION ──────────────────────────────────

    def reflect(
        self,
        task: str,
        result: str,
        context: str = "",
    ) -> ReflectionResult:
        """
        Ask the LLM to evaluate its own output.

        Args:
            task: The original task/prompt.
            result: The LLM's output to evaluate.
            context: Optional additional context for evaluation.

        Returns:
            ReflectionResult with quality_score, issues, improvements, should_retry.
        """
        user_content = f"""\
## Task
{task}

## Result to Evaluate
{result}
"""
        if context:
            user_content += f"\n## Additional Context\n{context}\n"

        user_content += """
## Your Evaluation
Evaluate the result against the task. Return ONLY a JSON object:
{
  "quality_score": 0.0-1.0,
  "issues": ["..."],
  "improvements": ["..."],
  "should_retry": true/false
}
"""

        try:
            messages = [
                Message(role="system", content=REFLECTION_SYSTEM_PROMPT),
                Message(role="user", content=user_content),
            ]

            response = self.llm_client.chat(messages, agent_id=AGENT_ID)
            return self._parse_reflection_response(response.content)

        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            return ReflectionResult(
                quality_score=0.0,
                issues=[f"Reflection engine error: {str(e)}"],
                improvements=[],
                should_retry=False,
                raw_response="",
            )

    def _parse_reflection_response(self, response_text: str) -> ReflectionResult:
        """
        Parse the LLM's reflection response into a ReflectionResult.

        Handles various formats: clean JSON, JSON in markdown fences, etc.
        """
        # Default result on parse failure
        default = ReflectionResult(
            quality_score=0.5,
            issues=["Could not parse reflection response"],
            improvements=[],
            should_retry=False,
            raw_response=response_text,
        )

        if not response_text or not response_text.strip():
            return default

        # Try to extract JSON from the response
        json_str = self._extract_json(response_text)
        if not json_str:
            return default

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return default

        # Validate and extract fields
        try:
            quality_score = float(data.get("quality_score", 0.5))
            quality_score = max(0.0, min(1.0, quality_score))  # Clamp to [0, 1]
        except (TypeError, ValueError):
            quality_score = 0.5

        issues = data.get("issues", [])
        if not isinstance(issues, list):
            issues = [str(issues)]

        improvements = data.get("improvements", [])
        if not isinstance(improvements, list):
            improvements = [str(improvements)]

        should_retry = bool(data.get("should_retry", quality_score < 0.6))

        return ReflectionResult(
            quality_score=quality_score,
            issues=[str(i) for i in issues],
            improvements=[str(i) for i in improvements],
            should_retry=should_retry,
            raw_response=response_text,
        )

    # ─── REACT LOOP ───────────────────────────────────────

    def react_loop(
        self,
        task: str,
        tools: Any = None,
        max_steps: int = 5,
    ) -> ReActResult:
        """
        Execute a full ReAct (Reason+Act) loop.

        Loop: Thought → Action → Observation → ... → Final Answer

        Each step:
            1. Ask LLM "What should I think/do next?" with available tools
            2. Parse response for THOUGHT/ACTION/OBSERVATION/FINAL_ANSWER
            3. Execute action if it's a tool call
            4. Feed observation back
            5. Continue until FINAL_ANSWER or max_steps

        Args:
            task: The task to accomplish.
            tools: A ToolRegistry instance with available tools.
            max_steps: Maximum number of reasoning steps.

        Returns:
            ReActResult with steps, final answer, and status.
        """
        start_time = time.time()

        # Build tool descriptions
        tool_descriptions = self._build_tool_descriptions(tools)

        # Format system prompt
        system_prompt = REACT_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descriptions
        )

        # Conversation history for the ReAct loop
        conversation: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Task: {task}"),
        ]

        steps: list[ReActStep] = []
        final_answer = ""
        success = False

        for step_num in range(1, max_steps + 1):
            step = ReActStep(step_number=step_num, timestamp=time.time())

            try:
                # Ask LLM for next thought/action
                response = self.llm_client.chat(conversation, agent_id=AGENT_ID)
                response_text = response.content

                if not response_text or not response_text.strip():
                    step.thought = "[No response from LLM]"
                    steps.append(step)
                    break

                # Parse the response
                parsed = self._parse_react_response(response_text)

                # Extract THOUGHT
                if parsed.get("thought"):
                    step.thought = parsed["thought"]

                # Check for FINAL_ANSWER
                if parsed.get("final_answer"):
                    final_answer = parsed["final_answer"]
                    step.thought = step.thought or "Reached final answer."
                    steps.append(step)
                    success = True
                    break

                # Extract ACTION
                if parsed.get("action"):
                    action_name, action_args = parsed["action"]
                    step.action = action_name
                    step.action_args = action_args

                    # Execute the action
                    observation = self._execute_action(action_name, action_args, tools)
                    step.observation = observation

                    # Add to conversation
                    conversation.append(Message(role="assistant", content=response_text))
                    conversation.append(
                        Message(
                            role="user",
                            content=f"OBSERVATION: {observation}",
                        )
                    )
                else:
                    # No action and no final answer — LLM just thought
                    conversation.append(Message(role="assistant", content=response_text))
                    # If LLM didn't produce an action or final answer, prompt it
                    if step_num < max_steps:
                        conversation.append(
                            Message(
                                role="user",
                                content="Continue. What action should you take next? "
                                        "Use the format: THOUGHT: ... ACTION: tool_name(args)",
                            )
                        )

                steps.append(step)

            except Exception as e:
                logger.error(f"ReAct step {step_num} failed: {e}")
                step.observation = f"[Error during step execution: {str(e)}]"
                steps.append(step)
                break

        elapsed = time.time() - start_time

        if not final_answer and steps:
            # Try to extract answer from last thought
            last_thought = steps[-1].thought
            if last_thought:
                final_answer = last_thought
            else:
                final_answer = "[ReAct loop ended without a final answer]"

        return ReActResult(
            task=task,
            steps=steps,
            final_answer=final_answer,
            total_steps=len(steps),
            success=success,
            elapsed=elapsed,
        )

    def _parse_react_response(self, response: str) -> dict:
        """
        Parse a ReAct response for THOUGHT, ACTION, and FINAL_ANSWER.

        Returns dict with keys: thought, action, final_answer
        Action is a tuple of (tool_name, args_dict) if present.
        """
        result: dict[str, Any] = {
            "thought": "",
            "action": None,
            "final_answer": "",
        }

        # Extract FINAL_ANSWER (highest priority — ends the loop)
        fa_match = re.search(
            r"FINAL_ANSWER\s*:\s*(.*)", response, re.DOTALL | re.IGNORECASE
        )
        if fa_match:
            result["final_answer"] = fa_match.group(1).strip()
            # Also extract any THOUGHT before the final answer
            before_fa = response[: fa_match.start()]
            thought_match = re.search(
                r"THOUGHT\s*:\s*(.*?)(?=ACTION|FINAL_ANSWER|$)",
                before_fa,
                re.DOTALL | re.IGNORECASE,
            )
            if thought_match:
                result["thought"] = thought_match.group(1).strip()
            return result

        # Extract THOUGHT
        thought_match = re.search(
            r"THOUGHT\s*:\s*(.*?)(?=ACTION|OBSERVATION|FINAL_ANSWER|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        # Extract ACTION
        action_match = re.search(
            r"ACTION\s*:\s*(\w+)\s*\((.*?)\)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if action_match:
            tool_name = action_match.group(1).strip()
            args_str = action_match.group(2).strip()

            # Parse arguments
            args = {}
            if args_str:
                try:
                    # Try JSON parse
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    # Try key=value parsing
                    for pair in args_str.split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            k = k.strip().strip('"').strip("'")
                            v = v.strip().strip('"').strip("'")
                            args[k] = v
                        else:
                            # Positional arg → use "arg_N" keys
                            arg_key = f"arg_{len(args)}"
                            args[arg_key] = pair.strip().strip('"').strip("'")

            result["action"] = (tool_name, args)

        return result

    def _execute_action(
        self,
        action_name: str,
        action_args: dict,
        tools: Any,
    ) -> str:
        """
        Execute a tool action and return the observation string.

        Args:
            action_name: Name of the tool to call.
            action_args: Arguments for the tool.
            tools: ToolRegistry instance.

        Returns:
            String observation from the tool execution.
        """
        if tools is None:
            return f"[No tool registry available. Action '{action_name}' not executed.]"

        if ToolRegistry is not None and not isinstance(tools, ToolRegistry):
            # Try to call it anyway if it has a dispatch method
            if not hasattr(tools, "dispatch"):
                return f"[Tool registry does not have a dispatch method. Action '{action_name}' not executed.]"

        try:
            result = tools.dispatch(action_name, **action_args)

            # Format result as observation string
            if isinstance(result, dict):
                # Truncate large outputs
                result_str = json.dumps(result, ensure_ascii=False, indent=2)
                if len(result_str) > 3000:
                    result_str = result_str[:3000] + "\n... [truncated]"
                return result_str
            else:
                return str(result)[:3000]

        except Exception as e:
            return f"[Tool '{action_name}' execution failed: {str(e)}]"

    def _build_tool_descriptions(self, tools: Any) -> str:
        """Build a formatted string of available tools for the system prompt."""
        if tools is None:
            return "No tools available."

        try:
            tool_list = tools.list_tools()
        except Exception:
            return "Tools available but could not enumerate."

        if not tool_list:
            return "No tools available."

        descriptions = []
        for tool in tool_list:
            name = tool.get("name", "?")
            desc = tool.get("description", "")
            params = tool.get("params", {})
            category = tool.get("category", "general")

            param_str = ", ".join(f"{k}: {v}" for k, v in params.items())
            descriptions.append(f"- {name}({param_str}) — {desc} [{category}]")

        return "\n".join(descriptions)

    # ─── SELF-CORRECTION ──────────────────────────────────

    def self_correct(self, task: str, code: str, error: str) -> str:
        """
        Given code and an error, produce corrected code.

        Args:
            task: The original task that the code was meant to solve.
            code: The code that produced the error.
            error: The error message or traceback.

        Returns:
            Corrected code string.
        """
        user_content = f"""\
## Original Task
{task}

## Code with Error
```
{code}
```

## Error Message
{error}

## Corrected Code
Return ONLY the corrected code. No explanations, no markdown fences.
"""

        try:
            messages = [
                Message(role="system", content=SELF_CORRECT_SYSTEM_PROMPT),
                Message(role="user", content=user_content),
            ]

            response = self.llm_client.chat(messages, agent_id=AGENT_ID)
            corrected = response.content.strip()

            # Strip markdown code fences if present
            corrected = self._strip_code_fences(corrected)

            return corrected

        except Exception as e:
            logger.error(f"Self-correction failed: {e}")
            return f"# Self-correction failed: {str(e)}\n# Original code:\n{code}"

    # ─── REFLECTIVE SELF-CORRECT LOOP ────────────────────

    def reflect_and_correct(
        self,
        task: str,
        result: str,
        context: str = "",
        max_attempts: int = 3,
    ) -> dict:
        """
        Reflect on output, and if quality is low, retry with improvements.

        This combines reflection with iterative improvement:
        1. Reflect on the result
        2. If should_retry, generate an improved version
        3. Reflect again on the improved version
        4. Repeat up to max_attempts

        Args:
            task: The original task.
            result: The initial result to evaluate.
            context: Optional context.
            max_attempts: Maximum improvement attempts.

        Returns:
            Dict with: best_result, best_score, attempts, history
        """
        history: list[dict] = []
        best_result = result
        best_score = 0.0
        current_result = result

        for attempt in range(1, max_attempts + 1):
            # Reflect
            reflection = self.reflect(task, current_result, context)

            history.append({
                "attempt": attempt,
                "quality_score": reflection.quality_score,
                "issues": reflection.issues,
                "improvements": reflection.improvements,
                "should_retry": reflection.should_retry,
            })

            if reflection.quality_score > best_score:
                best_score = reflection.quality_score
                best_result = current_result

            # If good enough, stop
            if not reflection.should_retry or reflection.quality_score >= 0.8:
                break

            # Generate improved version
            if attempt < max_attempts:
                improvements_str = "\n".join(
                    f"- {imp}" for imp in reflection.improvements
                )
                issues_str = "\n".join(
                    f"- {issue}" for issue in reflection.issues
                )

                improve_prompt = f"""\
## Task
{task}

## Current Result
{current_result}

## Issues Found
{issues_str}

## Suggested Improvements
{improvements_str}

Please provide an improved version that addresses the issues and incorporates the suggested improvements.
"""

                try:
                    messages = [
                        Message(
                            role="system",
                            content="You are an improvement engine. Provide an improved version of the given result. "
                                    "Address all listed issues and incorporate suggested improvements.",
                        ),
                        Message(role="user", content=improve_prompt),
                    ]

                    response = self.llm_client.chat(messages, agent_id=AGENT_ID)
                    current_result = response.content.strip()

                except Exception as e:
                    logger.error(f"Improvement attempt {attempt} failed: {e}")
                    break

        return {
            "best_result": best_result,
            "best_score": best_score,
            "attempts": len(history),
            "history": history,
        }

    # ─── HELPERS ──────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """
        Extract JSON from text, handling markdown fences and extra content.

        Tries in order:
        1. Direct JSON parse
        2. JSON inside ```json ... ``` fences
        3. JSON inside ``` ... ``` fences
        4. First { ... } block
        5. First [ ... ] block
        """
        text = text.strip()

        # Try direct parse
        try:
            json.loads(text)
            return text
        except (json.JSONDecodeError, ValueError):
            pass

        # Try ```json fences
        json_fence = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
        if json_fence:
            candidate = json_fence.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                pass

        # Try generic ``` fences
        generic_fence = re.search(r"```\s*(.*?)```", text, re.DOTALL)
        if generic_fence:
            candidate = generic_fence.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                pass

        # Try first { ... } block
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            candidate = brace_match.group(0)
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                pass

        # Try first [ ... ] block
        bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
        if bracket_match:
            candidate = bracket_match.group(0)
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    @staticmethod
    def _strip_code_fences(code: str) -> str:
        """Strip markdown code fences from code."""
        code = code.strip()

        # Remove ```language ... ``` fences
        fence_match = re.match(r"^```\w*\n(.*?)```$", code, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()

        # Remove opening and closing fences separately
        if code.startswith("```"):
            lines = code.split("\n")
            # Remove first line (opening fence)
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove last line (closing fence)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()

        return code


# ═══════════════════════════════════════════════════════════
# PLANNING ENGINE
# ═══════════════════════════════════════════════════════════

class PlanningEngine:
    """
    Planning engine for the NEXUS agent system.

    Creates step-by-step plans with agent/tool assignments
    and evaluates plan quality.

    Usage:
        llm = LLMClient()
        planner = PlanningEngine(llm_client=llm)

        plan = planner.plan("Build a web app", agents=["FORGE", "SCOUT"])
        evaluation = planner.evaluate_plan(plan, "Build a web app")
    """

    def __init__(self, llm_client: Any):
        """
        Initialize the PlanningEngine.

        Args:
            llm_client: An LLMClient instance for making LLM calls.
        """
        if LLMClient is not None and not isinstance(llm_client, LLMClient):
            logger.warning(
                f"llm_client is not an LLMClient instance (got {type(llm_client).__name__}). "
                "Proceeding anyway — ensure it has a .chat() method."
            )

        self.llm_client = llm_client

    def plan(
        self,
        task: str,
        available_agents: Optional[list[str]] = None,
        available_tools: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Create a step-by-step plan for the task.

        Args:
            task: The task to plan for.
            available_agents: List of available agent names (e.g., ["SCOUT", "FORGE"]).
            available_tools: List of available tool names (e.g., ["terminal", "web_search"]).

        Returns:
            List of step dicts: [{step, action, agent, tool, depends_on}]
        """
        # Default agents and tools
        agents = available_agents or ["NEXUS-0", "SCOUT", "FORGE", "LENS", "HERALD", "GHOST"]
        tools = available_tools or [
            "terminal", "read_file", "write_file", "web_search",
            "code_exec", "git", "http_request", "file_search",
        ]

        agents_str = ", ".join(agents)
        tools_str = ", ".join(tools)

        system_prompt = PLAN_SYSTEM_PROMPT.format(agents=agents_str, tools=tools_str)

        user_content = f"""\
Create a step-by-step plan for the following task:

## Task
{task}

## Available Agents
{agents_str}

## Available Tools
{tools_str}

Return the plan as a JSON array of step objects.
"""

        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_content),
            ]

            response = self.llm_client.chat(messages, agent_id=AGENT_ID)
            return self._parse_plan_response(response.content)

        except Exception as e:
            logger.error(f"Planning failed: {e}")
            return [{
                "step": 1,
                "action": f"Planning engine error: {str(e)}. Execute task directly.",
                "agent": "NEXUS-0",
                "tool": "",
                "depends_on": [],
            }]

    def evaluate_plan(self, plan: list[dict], task: str) -> dict:
        """
        Evaluate plan quality and suggest optimizations.

        Args:
            plan: List of step dicts from plan().
            task: The original task.

        Returns:
            Dict with: score, issues, optimized_plan
        """
        if not plan:
            return {
                "score": 0.0,
                "issues": ["Empty plan provided"],
                "optimized_plan": [],
            }

        plan_json = json.dumps(plan, ensure_ascii=False, indent=2)

        user_content = f"""\
## Task
{task}

## Plan to Evaluate
{plan_json}

Evaluate this plan for quality and suggest optimizations.
Return a JSON object with: score, issues, optimized_plan.
"""

        try:
            messages = [
                Message(role="system", content=PLAN_EVALUATE_SYSTEM_PROMPT),
                Message(role="user", content=user_content),
            ]

            response = self.llm_client.chat(messages, agent_id=AGENT_ID)
            return self._parse_evaluation_response(response.content)

        except Exception as e:
            logger.error(f"Plan evaluation failed: {e}")
            return {
                "score": 0.5,
                "issues": [f"Evaluation engine error: {str(e)}"],
                "optimized_plan": plan,
            }

    # ─── PARSE HELPERS ────────────────────────────────────

    def _parse_plan_response(self, response_text: str) -> list[dict]:
        """Parse LLM response into a list of plan step dicts."""
        if not response_text or not response_text.strip():
            return self._default_plan()

        # Extract JSON
        json_str = ReflectionEngine._extract_json(response_text)
        if not json_str:
            return self._default_plan()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return self._default_plan()

        # Ensure it's a list
        if isinstance(data, dict):
            # Might be wrapped in an object
            if "plan" in data:
                data = data["plan"]
            elif "steps" in data:
                data = data["steps"]
            else:
                data = [data]

        if not isinstance(data, list):
            return self._default_plan()

        # Validate and normalize each step
        validated_plan: list[dict] = []
        for i, step in enumerate(data):
            if not isinstance(step, dict):
                continue

            validated_step = {
                "step": step.get("step", i + 1),
                "action": str(step.get("action", "")),
                "agent": str(step.get("agent", "NEXUS-0")),
                "tool": str(step.get("tool", "")),
                "depends_on": step.get("depends_on", []),
            }

            # Ensure depends_on is a list
            if not isinstance(validated_step["depends_on"], list):
                validated_step["depends_on"] = []

            # Ensure step number is int
            try:
                validated_step["step"] = int(validated_step["step"])
            except (TypeError, ValueError):
                validated_step["step"] = i + 1

            validated_plan.append(validated_step)

        # Re-number steps if needed
        for i, step in enumerate(validated_plan):
            step["step"] = i + 1

        return validated_plan if validated_plan else self._default_plan()

    def _parse_evaluation_response(self, response_text: str) -> dict:
        """Parse LLM evaluation response into a structured dict."""
        default = {
            "score": 0.5,
            "issues": ["Could not parse evaluation response"],
            "optimized_plan": [],
        }

        if not response_text or not response_text.strip():
            return default

        json_str = ReflectionEngine._extract_json(response_text)
        if not json_str:
            return default

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return default

        if not isinstance(data, dict):
            return default

        # Extract score
        try:
            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
        except (TypeError, ValueError):
            score = 0.5

        # Extract issues
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            issues = [str(issues)]

        # Extract optimized plan
        optimized_plan = data.get("optimized_plan", [])
        if not isinstance(optimized_plan, list):
            optimized_plan = []

        return {
            "score": score,
            "issues": [str(i) for i in issues],
            "optimized_plan": optimized_plan,
        }

    @staticmethod
    def _default_plan() -> list[dict]:
        """Return a minimal default plan when parsing fails."""
        return [{
            "step": 1,
            "action": "Analyze and execute the task directly",
            "agent": "NEXUS-0",
            "tool": "",
            "depends_on": [],
        }]

    # ─── CONVENIENCE ──────────────────────────────────────

    def plan_and_evaluate(
        self,
        task: str,
        available_agents: Optional[list[str]] = None,
        available_tools: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a plan and evaluate it in one call.

        Returns the optimized plan if evaluation improves it,
        otherwise returns the original plan.

        Args:
            task: The task to plan for.
            available_agents: Optional list of agent names.
            available_tools: Optional list of tool names.

        Returns:
            Dict with: original_plan, evaluation, final_plan
        """
        original_plan = self.plan(task, available_agents, available_tools)
        evaluation = self.evaluate_plan(original_plan, task)

        # Use optimized plan if available and valid
        final_plan = evaluation.get("optimized_plan", [])
        if not final_plan or not isinstance(final_plan, list):
            final_plan = original_plan

        return {
            "original_plan": original_plan,
            "evaluation": evaluation,
            "final_plan": final_plan,
        }
