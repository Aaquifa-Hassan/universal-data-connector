import json
import re
import time
import logging
from openai import OpenAI
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any
from app.config import settings
from app.connectors.student_connector import StudentConnector
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector

logger = logging.getLogger(__name__)

# Initialize Router
router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    responses={404: {"description": "Not found"}},
)

# Initialize Local Ollama Client (OpenAI-compatible API)
client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="ollama", # API key is not required for local Ollama, but OpenAI client needs a value
    timeout=60.0,
)

# Small, fast model on local Ollama
MODEL_NAME = "gpt-oss:latest"


# ── Tool definitions (OpenAI tool-calling format) ──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_student_data",
            "description": "Get student course records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "batch": {"type": "string", "description": "Batch code, e.g. '22f2'"},
                    "course_code": {"type": "string", "description": "Course code, e.g. 'CS2003P'"},
                    "course_name": {"type": "string", "description": "Course name (partial match)"},
                    "term": {"type": "string", "description": "Term code, e.g. 'F1-2024'"},
                    "min_marks": {"type": "integer", "description": "Min marks filter"},
                    "limit": {"type": "integer", "description": "Max records (default 5)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_crm_data",
            "description": "Get CRM customer records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max records (default 5)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_support_data",
            "description": "Get support ticket records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max records (default 5)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_analytics_data",
            "description": "Get analytics metrics (page views, sessions, conversions, bounce rate, revenue).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max records (default 5)"}
                }
            }
        }
    },
]

SYSTEM_PROMPT = (
    "You are a concise data assistant with tools for: students, CRM, support tickets, analytics. "
    "Rules: Only call tools for data queries. For greetings/general chat, reply naturally without tools. "
    "Never fabricate data. Be brief and conversational. Match the user's language (English/Hindi)."
)


# ── Warmup: prime Ollama KV cache with system prompt + tools on startup ──
def _warmup_kv_cache():
    """Send a no-op request so Ollama caches the system prompt + tool schema prefix."""
    try:
        logger.info("Warming up Ollama KV cache...")
        t0 = time.time()
        client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "hi"}],
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1,
        )
        logger.info(f"KV cache warmup completed in {time.time() - t0:.2f}s")
    except Exception as e:
        logger.warning(f"KV cache warmup failed (non-fatal): {e}")


import threading as _threading
_threading.Thread(target=_warmup_kv_cache, daemon=True).start()

# In-memory session storage (OpenAI message format)
SESSIONS: Dict[str, list] = {}

# Define User Input Model
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    voice_mode: bool = False


# ── Keys to strip from tool results to reduce Pass 2 prompt tokens ──
_STRIP_KEYS = {"tags", "_index", "_of", "timestamp"}


def _slim_record(record: dict) -> dict:
    """Remove noisy keys from a data record to reduce token count."""
    return {k: v for k, v in record.items() if k not in _STRIP_KEYS}


def _execute_tool(function_name: str, function_args: dict) -> list:
    """Execute the named connector tool and return data."""
    if function_name == "get_student_data":
        return StudentConnector().fetch(**function_args)
    elif function_name == "get_crm_data":
        return CRMConnector().fetch(**function_args)
    elif function_name == "get_support_data":
        return SupportConnector().fetch(**function_args)
    elif function_name == "get_analytics_data":
        return AnalyticsConnector().fetch(**function_args)
    return []


@router.post("/", response_model=Dict[str, Any])
def chat_with_data(request: ChatRequest, background_tasks: BackgroundTasks):
    t_overall_start = time.time()
    session_id = request.session_id
    background_tasks.add_task(lambda: logger.info(f"[{session_id}] Overall request latency: {time.time() - t_overall_start:.2f} seconds."))

    # Initialize history with system prompt
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    history = SESSIONS[session_id]

    try:
        # Append user message
        history.append({"role": "user", "content": request.message})

        # 1. First call — may return a tool call (Groq supports native tool calling)
        logger.info(f"[{session_id}] Starting first LLM inference pass...")
        t0 = time.time()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=history,
            tools=TOOLS,
            tool_choice="auto",
        )
        t1 = time.time()
        
        usage = response.usage
        if usage:
            logger.info(f"[{session_id}] Pass 1 Tokens - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}, Total: {usage.total_tokens}")
            
        logger.info(f"[{session_id}] First LLM inference completed in {t1 - t0:.2f} seconds.")

        message = response.choices[0].message

        # 2. Check for tool call
        if message.tool_calls:
            # Append the assistant's tool-call message to history
            history.append(message)

            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments or "{}")

            logger.info(f"[{session_id}] Tool called: {function_name} with args: {function_args}")
            print(f"Tool called: {function_name} with args: {function_args}")

            # 3. Execute the tool
            t2 = time.time()
            data_response = _execute_tool(function_name, function_args)
            t3 = time.time()
            logger.info(f"[{session_id}] Tool '{function_name}' executed in {t3 - t2:.2f} seconds.")

            # 4. Append slimmed tool result to history (fewer tokens for Pass 2)
            slimmed = [_slim_record(r) for r in data_response]
            history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps({"result": slimmed}, default=str),
            })

            # 5. Get final natural language response (no tools needed here — saves ~400 prompt tokens)
            logger.info(f"[{session_id}] Starting second LLM inference pass for final synthesis...")
            t4 = time.time()
            final_response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=history,
            )
            t5 = time.time()
            
            final_usage = final_response.usage
            if final_usage:
                logger.info(f"[{session_id}] Pass 2 Tokens - Prompt: {final_usage.prompt_tokens}, Completion: {final_usage.completion_tokens}, Total: {final_usage.total_tokens}")
                
            logger.info(f"[{session_id}] Second LLM inference completed in {t5 - t4:.2f} seconds.")

            final_message = final_response.choices[0].message
            response_text = final_message.content or "Here are the results."

            # Append final assistant message to history
            history.append({"role": "assistant", "content": response_text})

            print(f"Final response: {response_text[:120]}")

            return {
                "response": response_text,
                "data": data_response,
            }

        else:
            # No tool call — plain text response
            response_text = message.content or "I'm not sure how to help with that."
            history.append({"role": "assistant", "content": response_text})

            return {
                "response": response_text,
                "data": [],
            }

    except Exception as e:
        print(f"Groq Error: {str(e)}. Falling back to local keyword matching...")

        msg = request.message.lower()

        # ── Detect which data source to use ──
        is_crm = any(w in msg for w in ['crm', 'customer', 'client', 'company', 'revenue', 'sales', 'lead'])
        is_support = any(w in msg for w in ['support', 'ticket', 'issue', 'complaint', 'priority', 'open ticket', 'bug'])
        is_analytics = any(w in msg for w in ['analytics', 'metric', 'page view', 'session', 'conversion', 'bounce', 'traffic'])

        # ── Extract limit ──
        limit_match = re.search(r'\b(\d+)\b', msg)
        limit = int(limit_match.group(1)) if limit_match else 5

        error_str = str(e)
        if '429' in error_str or 'rate' in error_str.lower():
            reason = f"API rate limit reached ({error_str})"
        elif '503' in error_str or 'unavailable' in error_str.lower():
            reason = f"AI service temporarily unavailable ({error_str})"
        elif '504' in error_str or 'timeout' in error_str.lower():
            reason = f"AI service timed out ({error_str})"
        elif 'auth' in error_str.lower() or '401' in error_str or '403' in error_str:
            reason = f"API key issue ({error_str})"
        else:
            reason = f"AI service error: {error_str}"

        if is_crm:
            connector = CRMConnector()
            data = connector.fetch(limit=limit)
            return {
                "response": f"I've checked the customer list for you. {reason if 'error' in reason else ''} Here are the details for {len(data)} customers.",
                "data": data
            }
        elif is_support:
            connector = SupportConnector()
            data = connector.fetch(limit=limit)
            return {
                "response": f"I've looked through the support tickets. {reason if 'error' in reason else ''} I found {len(data)} tickets that might interest you.",
                "data": data
            }
        elif is_analytics:
            connector = AnalyticsConnector()
            data = connector.fetch(limit=limit)
            return {
                "response": f"I've pulled the analytics metrics you asked for. {reason if 'error' in reason else ''} Here is the summary of the latest {len(data)} data points.",
                "data": data
            }
        else:
            connector = StudentConnector()
            filters = {}

            batch_match = re.search(r'batch\s+([\w\s]+?)(?:\s+(?:course|term|grade|above|over|min|with|and|$))', msg)
            if not batch_match:
                batch_match = re.search(r'batch\s+([\w]+(?:\s+[\w]+)?)', msg)
            if batch_match:
                filters['batch'] = batch_match.group(1).replace(' ', '')

            course_match = re.search(r'course\s+(\w+)', msg)
            if course_match:
                filters['course_code'] = course_match.group(1)

            term_match = re.search(r'term\s+([\w-]+)', msg)
            if term_match:
                filters['term'] = term_match.group(1)

            marks_match = re.search(r'(?:above|over|min(?:imum)?|more than|>\s*)\s*(\d+)\s*(?:marks)?', msg)
            if marks_match:
                filters['min_marks'] = int(marks_match.group(1))

            filters['limit'] = limit
            data = connector.fetch(**filters)

            grade_match = re.search(r'grade\s+([A-Za-z+]+)', msg)
            if grade_match:
                target_grade = grade_match.group(1).upper()
                data = [d for d in data if d.get('grade', '').upper() == target_grade]

            return {
                "response": f"I've found {len(data)} student courses matching your request. {reason if 'error' in reason else ''} Here is the information.",
                "data": data
            }


# ── SSE Streaming endpoint with filler phrases ──

import random
from fastapi.responses import StreamingResponse
import queue
import threading

FILLER_PHRASES = [
    "Sure, let me check that for you...",
    "One moment, pulling up the details...",
    "Hang on, I'm looking into it...",
    "Let me grab that information real quick...",
    "Just a sec, fetching the data...",
    "On it! Give me a moment...",
    "Let me look that up for you...",
    "Working on it, one second...",
    "Sure thing, let me find that...",
    "Checking the records now...",
]


def _sse(event: str, data: dict) -> str:
    """Format a dict as an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _run_chat_pipeline(request: ChatRequest, result_queue: queue.Queue):
    """Run the full LLM chat pipeline and put the result into the queue."""
    try:
        t_overall_start = time.time()
        session_id = request.session_id

        if session_id not in SESSIONS:
            SESSIONS[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

        history = SESSIONS[session_id]
        history.append({"role": "user", "content": request.message})

        # Pass 1: Tool selection
        logger.info(f"[{session_id}] [SSE] Starting Pass 1...")
        t0 = time.time()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=history,
            tools=TOOLS,
            tool_choice="auto",
        )
        t1 = time.time()
        usage = response.usage
        if usage:
            logger.info(f"[{session_id}] [SSE] Pass 1 Tokens - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}, Total: {usage.total_tokens}")
        logger.info(f"[{session_id}] [SSE] Pass 1 completed in {t1 - t0:.2f}s")

        message = response.choices[0].message

        if message.tool_calls:
            history.append(message)
            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments or "{}")
            logger.info(f"[{session_id}] [SSE] Tool: {function_name}({function_args})")

            t2 = time.time()
            data_response = _execute_tool(function_name, function_args)
            t3 = time.time()
            logger.info(f"[{session_id}] [SSE] Tool executed in {t3 - t2:.2f}s")

            slimmed = [_slim_record(r) for r in data_response]
            history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps({"result": slimmed}, default=str),
            })

            # Pass 2: Synthesis
            logger.info(f"[{session_id}] [SSE] Starting Pass 2...")
            t4 = time.time()
            final_response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=history,
            )
            t5 = time.time()
            final_usage = final_response.usage
            if final_usage:
                logger.info(f"[{session_id}] [SSE] Pass 2 Tokens - Prompt: {final_usage.prompt_tokens}, Completion: {final_usage.completion_tokens}, Total: {final_usage.total_tokens}")
            logger.info(f"[{session_id}] [SSE] Pass 2 completed in {t5 - t4:.2f}s")

            response_text = final_response.choices[0].message.content or "Here are the results."
            history.append({"role": "assistant", "content": response_text})

            logger.info(f"[{session_id}] [SSE] Overall: {time.time() - t_overall_start:.2f}s")
            result_queue.put({"response": response_text, "data": data_response})
        else:
            response_text = message.content or "I'm not sure how to help with that."
            history.append({"role": "assistant", "content": response_text})
            result_queue.put({"response": response_text, "data": []})

    except Exception as e:
        logger.error(f"[SSE] Pipeline error: {e}")
        result_queue.put({"response": f"Sorry, something went wrong: {e}", "data": []})


def _stream_with_filler(request: ChatRequest):
    """Generator: yield filler immediately, then yield LLM result when ready."""
    # 1. Immediately yield a random filler phrase
    filler = random.choice(FILLER_PHRASES)
    yield _sse("filler", {"text": filler})

    # 2. Run the heavy LLM pipeline in a background thread
    result_q: queue.Queue = queue.Queue()
    worker = threading.Thread(target=_run_chat_pipeline, args=(request, result_q), daemon=True)
    worker.start()
    worker.join()  # wait for completion

    # 3. Yield the actual result
    result = result_q.get()
    yield _sse("response", result)

    # 4. Done
    yield _sse("done", {"status": "complete"})


@router.post("/stream")
def chat_stream(request: ChatRequest):
    """
    SSE streaming chat endpoint.

    Immediately returns a random filler/waiting phrase, then streams
    the actual LLM response once processing is complete.

    Events:
    - `filler`: Instant waiting phrase to play as audio (masks latency)
    - `response`: The actual LLM response + data
    - `done`: Stream complete
    """
    return StreamingResponse(
        _stream_with_filler(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
