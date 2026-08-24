"""Local smoke test — runs the agent against real ClickHouse + real Gemini, no deploy."""
import asyncio

from google.adk.runners import InMemoryRunner
from google.genai import types

from shorts_studio_agent import root_agent


async def main():
    runner = InMemoryRunner(agent=root_agent, app_name="clickcuts_local_test")
    session = await runner.session_service.create_session(
        app_name="clickcuts_local_test", user_id="hun"
    )
    prompt = (
        "What narrative structure and thinker should the next episode use? "
        "Ground it in the data."
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    async for event in runner.run_async(
        user_id="hun", session_id=session.id, new_message=message
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "function_call", None):
                    print(f"[TOOL CALL] {part.function_call.name}({dict(part.function_call.args or {})})")
                if getattr(part, "function_response", None):
                    print(f"[TOOL RESULT] {part.function_response.name} -> {str(part.function_response.response)[:300]}")
                if getattr(part, "text", None):
                    print(f"[TEXT] {part.text}")


if __name__ == "__main__":
    asyncio.run(main())
