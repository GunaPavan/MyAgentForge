"""
MyAgentForge Demo — Run a task programmatically without the web UI.

Usage:
    python examples/demo.py "Create a Python calculator with add, subtract, multiply, divide"
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.swarm import Swarm


async def main():
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Create a simple Python calculator"

    print(f"\n{'='*60}")
    print(f"  MyAgentForge — AI Agent Swarm")
    print(f"{'='*60}")
    print(f"\n  Task: {task}\n")
    print(f"{'='*60}\n")

    swarm = Swarm()

    async for event in swarm.run(task):
        if event.type == "agent_status":
            status = event.data["status"].upper()
            agent = event.data["agent"].capitalize()
            icon = {"working": "[*]", "done": "[+]", "idle": "[ ]"}.get(event.data["status"], "[?]")
            print(f"  {icon} {agent}: {status}")

        elif event.type == "message":
            sender = event.data["sender"].upper()
            receiver = event.data["receiver"].upper()
            content = event.data["content"]
            print(f"\n  --- {sender} -> {receiver} ---")
            # Print first 300 chars
            preview = content[:300] + ("..." if len(content) > 300 else "")
            for line in preview.split("\n"):
                print(f"  | {line}")

        elif event.type == "code_output":
            files = event.data["files"]
            print(f"\n  {'='*40}")
            print(f"  CODE OUTPUT ({len(files)} files)")
            print(f"  {'='*40}")
            for fname, code in files.items():
                print(f"\n  --- {fname} ---")
                for line in code.split("\n")[:30]:
                    print(f"  | {line}")
                if len(code.split("\n")) > 30:
                    print(f"  | ... ({len(code.split(chr(10)))} lines total)")

        elif event.type == "task_status":
            if event.data["status"] == "completed":
                print(f"\n  {'='*60}")
                print(f"  TASK COMPLETED SUCCESSFULLY")
                print(f"  {'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
