import os
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# Supports any OpenAI-compatible API: OpenAI, Groq (free), Ollama (local), Together, etc.
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
MAX_REVIEW_ITERATIONS = int(os.getenv("MAX_REVIEW_ITERATIONS", "1"))
SKIP_TESTER = os.getenv("SKIP_TESTER", "false").lower() == "true"
COMBINE_ORCHESTRATOR = os.getenv("COMBINE_ORCHESTRATOR", "true").lower() == "true"
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=LLM_TIMEOUT)


def _build_params(system_prompt: str, user_prompt: str, stream: bool = False) -> dict:
    params = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    if MAX_TOKENS > 0:
        params["max_tokens"] = MAX_TOKENS
    if stream:
        params["stream"] = True
    return params


async def llm_call(system_prompt: str, user_prompt: str) -> str:
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(**_build_params(system_prompt, user_prompt)),
            timeout=LLM_TIMEOUT,
        )
        return response.choices[0].message.content or ""
    except asyncio.TimeoutError:
        return "[LLM call timed out after {}s]".format(LLM_TIMEOUT)
    except Exception as e:
        return f"[LLM error: {type(e).__name__}: {str(e)[:200]}]"


async def llm_stream(system_prompt: str, user_prompt: str):
    """Stream LLM response token by token. Yields text chunks."""
    try:
        stream = await client.chat.completions.create(
            **_build_params(system_prompt, user_prompt, stream=True)
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"[LLM error: {type(e).__name__}: {str(e)[:200]}]"
