import json
import os

skills = {
    "web_research": {"pattern": "Use SCOUT with web_search, triangulate 2+ sources", "description": "Web research with source triangulation"},
    "code_debug": {"pattern": "Use FORGE with error_root_cause skill. Read error, identify cause, fix, validate.", "description": "Debug code by root cause analysis"},
    "code_review": {"pattern": "Use LENS with devil_advocate and failure_mode_analysis skills", "description": "Critical code review"},
    "task_planning": {"pattern": "Decompose into DAG, parallel independent tasks, sequential dependencies", "description": "Plan complex multi-step tasks"},
}

os.makedirs("memory/skills", exist_ok=True)
for name, data in skills.items():
    data["updated"] = 1700000000
    with open(f"memory/skills/{name}.json", "w") as f:
        json.dump(data, f, indent=2)

print(f"Default skills installed: {len(skills)}")
