"""
NEXUS v7 — CLI Interface
Minimal CLI for testing and direct interaction.
"""

import sys
import yaml
import logging

from nexus.core.agent import NexusAgent


def main():
    """Run NEXUS in CLI mode for testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Create agent
    agent = NexusAgent(config)

    print("NEXUS v7 — CLI Mode")
    print(f"Soul: {agent.soul.personality.get('name', 'Toti')}")
    print(f"Tools: {', '.join(agent.tools.list_tools())}")
    print(f"Models: {', '.join(agent.llm.models.keys())}")
    print("Type 'quit' to exit, 'stats' for stats.\n")

    user_id = "cli_user"

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if user_input.lower() == "stats":
                print(f"Stats: {agent.stats()}")
                print(f"Memory: {agent.memory.stats()}")
                print(f"LLM: {agent.llm.stats()}")
                continue
            if user_input.lower() == "clear":
                agent.memory.clear()
                print("Memory cleared.")
                continue

            response = agent.process(user_input, user_id=user_id)
            print(f"\nToti: {response}\n")

    finally:
        agent.shutdown()
        print("\nNEXUS shut down.")


if __name__ == "__main__":
    main()