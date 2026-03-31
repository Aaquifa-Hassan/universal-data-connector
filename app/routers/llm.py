"""
LLM Router — Unified voice/chat assistant powered by Groq.

Conversation flow:
  1. Greet → authenticate (name + customer ID)
  2. Ask reason for call (support or CRM/product)
  3. Route to the appropriate scenario and call tools from UnifiedConnector
  4. Apply business rules inside the connector — LLM just reads the result
  5. Respond in 1-2 voice-optimised sentences
"""

import json
import re
import io
import edge_tts
from groq import Groq
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.connectors.unified_connector import UnifiedConnector, ConfigurationError, unified_connector
from app.services.metadata_service import metadata_service
from app.services.cache import data_cache, make_cache_key

# ── Router ─────────────────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    responses={404: {"description": "Not found"}},
)

# ── Groq client ────────────────────────────────────────────────────────────────

client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None
if not client:
    print("WARNING: GROQ_API_KEY not configured.")

MODEL_NAME = "llama-3.1-8b-instant"

# Word-to-number map — handles LLM passing 'one', 'two' etc. instead of digits
_WORD_NUM = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "zero": "0",
}

# ── Tool definitions (12 tools — one per UnifiedConnector method) ──────────────

TOOLS = [
    # ── CRM / Salesforce ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "authenticate_user",
            "description": (
                "Verify a caller's identity in our warehouse records using their customer ID. "
                "ALWAYS call this first before accessing any customer data. "
                "Call it as soon as the user provides their customer ID (e.g. they say 'one' → pass 'CUST-001')."
            ),
            "parameters": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": (
                            "The customer ID. Normalise before passing: if user says 'one' use 'CUST-001', "
                            "'two' → 'CUST-002', 'cust zero zero one' → 'CUST-001'. "
                            "Always format as CUST-XXX with 3-digit zero-padded number."
                        )
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_orders",
            "description": "Get a list of recent orders for an authenticated customer from our records. Use this if the customer doesn't have their order number ready.",
            "parameters": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                    "limit": {"type": "integer", "description": "Number of orders to return (default 5)."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": "Fetch comprehensive details for an order, including products, shipping dates, status, and pricing.",
            "parameters": {
                "type": "object",
                "required": ["customer_id", "order_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                    "order_id": {
                        "type": "string",
                        "description": "The Order ID provided by the customer (e.g., ORD-1)."
                    }
                }
            }
        }
    },
    # update_customer_profile removed for scope reduction
    {
        "type": "function",
        "function": {
            "name": "initiate_refund",
            "description": (
                "Initiate a refund for an order. Only call after check_expiry confirms "
                "the product is expired and the recommended_resolution is 'refund'."
            ),
            "parameters": {
                "type": "object",
                "required": ["order_id", "customer_id"],
                "properties": {
                    "order_id":    {"type": "string"},
                    "customer_id": {"type": "string"},
                    "reason":      {"type": "string", "description": "Short reason (e.g. 'Expired product')."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_exchange",
            "description": (
                "Initiate a product exchange. Only call after check_expiry confirms "
                "the recommended_resolution is 'exchange'."
            ),
            "parameters": {
                "type": "object",
                "required": ["order_id", "customer_id"],
                "properties": {
                    "order_id":    {"type": "string"},
                    "customer_id": {"type": "string"},
                    "reason":      {"type": "string"}
                }
            }
        }
    },
    # Ticket tools: check, raise, escalate
    {
        "type": "function",
        "function": {
            "name": "check_ticket_status",
            "description": (
                "Fetch the status and ETA of an existing support ticket. "
                "Call ONLY after the user provides a ticket number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "The support ticket ID (e.g., TICK-1001)"},
                    "customer_id": {"type": "string"}
                },
                "required": ["ticket_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_snowflake_tables",
            "description": "List all available tables in the Snowflake data warehouse. Use this to discover what data is available.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "preview_snowflake_table",
            "description": "Preview the first few rows of a specific Snowflake table to understand its structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "The name of the table to preview."},
                    "limit": {"type": "integer", "description": "Number of rows to preview (default 5)."}
                },
                "required": ["table_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_snowflake",
            "description": "Execute a raw SQL query on Snowflake. Use this only if you know the table structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "The SQL query to execute."}
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "raise_support_ticket",
            "description": (
                "Create a new Freshdesk support ticket. "
                "Call when the user has a new issue and has NOT raised a ticket yet."
            ),
            "parameters": {
                "type": "object",
                "required": ["customer_id", "subject", "description"],
                "properties": {
                    "customer_id": {"type": "string"},
                    "subject":     {"type": "string", "description": "Short issue title."},
                    "description": {"type": "string", "description": "Full issue description from the user."},
                    "email":       {"type": "string"},
                    "priority": {
                        "type": "integer",
                        "description": "1=low, 2=medium, 3=high, 4=urgent. Default 2."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_ticket",
            "description": (
                "Escalate an existing ticket to urgent priority. "
                "Use when the customer is frustrated, says it's been days, or explicitly asks to escalate."
            ),
            "parameters": {
                "type": "object",
                "required": ["ticket_id"],
                "properties": {
                    "ticket_id":   {"type": "string"},
                    "customer_id": {"type": "string"}
                }
            }
        }
    },
    # get_known_issues removed for scope reduction
]

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are Aria, a warm and empathetic voice-first customer service assistant. Our primary system of record is the Snowflake Data Warehouse.

### CRITICAL: AUTHENTICATION FIRST
1. **Greeting**: "Hey there! This is Aria. Before we get started, could I just grab your customer number (like CUST-1)?"
2. **Wait for ID**: Do NOT call any other tool or acknowledge any problem until `authenticate_user` succeeds.
3. **Post-Auth**: "Got it, thanks [Name]! Now, how can I help you today?" (If they mentioned an issue earlier, acknowledge it now with empathy).

### YOUR CORE FLOW (After Auth):
- **Lookup**: If they ask about an order or report a problem, ask for the order number (e.g., ORD-1). Use `get_recent_orders` if they need help finding it.
- **Details**: Use `get_order_details` to fetch order details. Acknowledge the order first and ask what they want to know before revealing details.
- **Action**: Call `initiate_refund` or `initiate_exchange` only if confirmed by the user AND valid per our records.

### GUIDELINES:
- **Strict Sequence**: Authenticate -> Identification -> Resolution.
- **No Jargon**: Never say "Snowflake", "API", or "Database". Say "our records".
- **Concise**: Responses under 25 words for voice. Natural fillers like "Hmm", "Ah".
"""

# ── Session storage ────────────────────────────────────────────────────────────

SESSIONS: Dict[str, list] = {}

# ── Request models ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    voice_mode: bool = False

class TTSRequest(BaseModel):
    text: str
    lang: str = "en"

# ── LLM helpers ────────────────────────────────────────────────────────────────

# All known tool names (reduced scope)
_TOOL_NAMES = {
    "authenticate_user", "get_order_details", "initiate_refund",
    "initiate_exchange", "check_ticket_status",
    "raise_support_ticket", "escalate_ticket",
    "list_snowflake_tables", "preview_snowflake_table", "query_snowflake"
}

def _sanitize_response(text: str) -> str:
    """
    Strip tool-call artifacts the LLM accidentally narrates:
      - JSON:           {"customer_id": "CUST-004"}
      - key=value:      function = CUST_001
      - function calls: authenticate_user(...)  or bare: authenticate_user
      - underscore IDs: CUST_001 -> CUST-001
    """
    import re
    clean_lines = []
    for line in text.splitlines():
        s = line.strip()
        # Drop lines that are or contain tool-call narration
        if re.search(r'\bfunction\s*[=:(]', s, re.IGNORECASE):
            continue
        if re.match(r'^[\w_]+\s*=\s*["\w{]', s):       # key = value (single word key)
            continue
        if re.search(r'\b\w[\w ]*\s*=\s*["\w]', s) and len(s) < 80:  # multi-word key=value, short line
            continue
        if re.match(r'^[a-z_]+\([^)]*\)\s*$', s):      # function call with ()
            continue
        if s.lower() in _TOOL_NAMES:                    # bare tool name alone on a line
            continue
        # Line starts with a tool name followed by args (e.g. 'get_order_details customer_id=...')
        first_word = s.split()[0].lower() if s else ''
        if first_word in _TOOL_NAMES:
            continue
        clean_lines.append(line)
    text = '\n'.join(clean_lines)
    # Remove inline JSON objects  {...}
    text = re.sub(r'\{[^{}]*\}', '', text)
    # Remove inline JSON arrays  [...]
    text = re.sub(r'\[[^\[\]]*\]', '', text)
    # Convert underscore IDs to dash: CUST_001 -> CUST-001
    text = re.sub(r'\b([A-Z]+)_(\d+)\b', r'\1-\2', text)
    # Clean up whitespace artefacts
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'^\s*[,\.]\s*', '', text, flags=re.MULTILINE)
    result = text.strip()
    # Fallback: if nothing left (or only a tool name survived), return a safe default
    if not result or result.lower() in _TOOL_NAMES:
        result = "I've taken care of that. How can I help you further?"
    return result


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_llm(messages: list, tools: Optional[list] = None,
               tool_choice: str = "auto", max_tokens: int = 250):
    """Call the Groq LLM with optional tool definitions."""
    return client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        tools=tools or [],
        tool_choice=tool_choice if tools else "none",
        max_tokens=max_tokens,
        temperature=0.0,
    )


async def _execute_tool(function_name: str, function_args: dict) -> dict:
    """Route a tool call to the corresponding UnifiedConnector method (async)."""
    import re
    if not isinstance(function_args, dict):
        function_args = {}


    def _normalise(s: str) -> str:
        words = str(s).lower().split()
        return " ".join(_WORD_NUM.get(w, w) for w in words)

    if "customer_id" in function_args:
        cid = _normalise(function_args["customer_id"])
        match = re.search(r'(\d+)', cid)
        if match:
            function_args["customer_id"] = f"CUST-{int(match.group(1)):03d}"
    if "order_id" in function_args:
        oid = _normalise(function_args["order_id"])
        match = re.search(r'(\d+)', oid)
        if match:
            function_args["order_id"] = f"ORD-{match.group(1)}"
    if "ticket_id" in function_args:
        tid = _normalise(function_args["ticket_id"])
        match = re.search(r'(\d+)', tid)
        if match:
            function_args["ticket_id"] = f"TICK-{match.group(1)}"


    cache_key = make_cache_key(function_name, **function_args)
    cached_result = data_cache.get(cache_key)
    if cached_result:
        print(f"[LLM ROUTER] Cache HIT for tool: {function_name}")
        return cached_result

    print(f"[LLM ROUTER] Cache MISS for tool: {function_name}")
    uc = unified_connector
    dispatch = {
        # Snowflake-Native CRM/E-commerce
        "authenticate_user":       uc.authenticate_user,
        "get_recent_orders":       uc.get_customer_orders,
        "get_order_details":        uc.get_order_details,
        "initiate_refund":         uc.initiate_refund,
        "initiate_exchange":       uc.initiate_exchange,
        # Snowflake Metadata/Query
        "list_snowflake_tables":   uc.list_snowflake_tables,
        "preview_snowflake_table": uc.preview_snowflake_table,
        "query_snowflake":         uc.query_snowflake,
    }
    fn = dispatch.get(function_name)
    if fn is None:
        return {"success": False, "data": {}, "message": f"Unknown tool: {function_name}"}
    try:
        print(f"[DEBUG] Calling {function_name} with args: {function_args}")
        result = await fn(**function_args)
        print(f"[DEBUG] {function_name} result: {result}")
        if result.get("success"):
            data_cache.set(cache_key, result)
        return result
    except ConfigurationError as ce:
        print(f"[DEBUG] ConfigurationError: {ce}")
        return {"success": False, "data": {}, "message": str(ce)}
    except TypeError as te:
        print(f"[DEBUG] TypeError: {te}")
        return {"success": False, "data": {}, "message": f"Tool call error: {te}"}

# ── TTS endpoint ───────────────────────────────────────────────────────────────

@router.post("/tts")
async def text_to_speech(request: TTSRequest):
    """Generate audio from text using edge-tts and return as a stream."""
    print(f"TTS Request: {request.text[:60]}...")
    try:
        import re as _re
        clean_text = request.text.replace("_", " ")
        # Strip parenthetical stage directions e.g. (pause), (Pause), (laughs)
        clean_text = _re.sub(r'\(\s*\w[\w\s]*\)', '', clean_text)
        clean_text = _re.sub(r'\s{2,}', ' ', clean_text).strip()
        is_hindi = any("\u0900" <= c <= "\u097F" for c in clean_text)
        voice = "hi-IN-SwaraNeural" if is_hindi else "en-US-MichelleNeural"
        communicate = edge_tts.Communicate(clean_text, voice, rate="-5%")
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_stream.write(chunk["data"])
        audio_stream.seek(0)
        return StreamingResponse(audio_stream, media_type="audio/mpeg")
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

# ── Main chat endpoint ─────────────────────────────────────────────────────────

@router.post("/", response_model=Dict[str, Any])
async def chat_with_data(request: ChatRequest):
    session_id = request.session_id
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    history = SESSIONS[session_id]

    async def _stream_response():
        try:
            import re as _re
            nonlocal history

            def _extract_customer_id(msg: str) -> Optional[str]:
                """Return normalised CUST-XXX if message looks like a customer number, else None."""
                tokens = msg.lower().strip().split()
                normalised = " ".join(_WORD_NUM.get(t, t) for t in tokens)
                # Match an explicit CUST-NNN pattern
                m = _re.search(r'cust[-\s]?(\d+)', normalised, _re.IGNORECASE)
                if m:
                    return f"CUST-{int(m.group(1)):03d}"
                # Match a bare number (digits or single word-number)
                m = _re.fullmatch(r'\s*(\d+)\s*', normalised)
                if m:
                    return f"CUST-{int(m.group(1)):03d}"
                # Single recognised word-number alone
                if len(tokens) == 1 and tokens[0] in _WORD_NUM:
                    return f"CUST-{int(_WORD_NUM[tokens[0]]):03d}"
                return None

            def _get_authenticated_id(hist: list) -> Optional[str]:
                """Return the CUST-XXX string if already authenticated."""
                for m in hist:
                    # Robust check for role: handles both dicts and Pydantic models (though history should be dicts now)
                    role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
                    if role == "tool":
                        try:
                            import json as _json
                            content = m.get("content", "{}") if isinstance(m, dict) else getattr(m, "content", "{}")
                            data = _json.loads(content)
                            if data.get("success") and data.get("data", {}).get("customer_id"):
                                return data["data"]["customer_id"]
                        except Exception:
                            pass
                return None

            # ── Parallel Metadata & Pre-Auth Logic ───────────────────────────────
            # Define SQL/Metadata intent keywords to keep context retrieval lazy
            METADATA_KEYWORDS = {"sql", "table", "schema", "data", "database", "query", "record", "list", "show", "preview"}
            has_metadata_intent = any(kw in request.message.lower() for kw in METADATA_KEYWORDS)
            
            async def _get_metadata():
                if has_metadata_intent:
                    return await metadata_service.get_context_for_query(request.message)
                return None

            # Run metadata retrieval and pre-auth check in parallel
            context_task = asyncio.create_task(_get_metadata())
            
            candidate_id = _extract_customer_id(request.message)
            existing_id = _get_authenticated_id(history)

            # If metadata is retrieved, append it to history
            context = await context_task
            if context:
                history.append({
                    "role": "system",
                    "content": f"SYSTEM CONTEXT (Snowflake Datalake):\n{context}\nUse this exact schema when generating SQL queries or discussing our data."
                })

            # If user provides a DIFFERENT ID, force reset to avoid identity mixing
            if candidate_id and existing_id and candidate_id != existing_id:
                print(f"[SESSION] Identity switch detected: {existing_id} -> {candidate_id}. Resetting.")
                history = [{"role": "system", "content": SYSTEM_PROMPT}]
                SESSIONS[session_id] = history
                existing_id = None

            if candidate_id and not existing_id:
                print(f"[PRE-AUTH] Detected customer number: {candidate_id}")
                auth_result = await _execute_tool("authenticate_user", {"customer_id": candidate_id})
                print(f"[PRE-AUTH] Auth result: {auth_result}")

                if auth_result.get("success"):
                    # Inject a synthetic tool exchange into history
                    import json as _json, uuid as _uuid
                    tool_call_id = f"preauth_{_uuid.uuid4().hex[:8]}"
                    # Synthetic assistant message that "called" the tool
                    history.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": "authenticate_user",
                                "arguments": _json.dumps({"customer_id": candidate_id})
                            }
                        }]
                    })
                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": _json.dumps(auth_result, default=str),
                    })
                    # Snowflake TPC-H names are 'Customer#000000087' — make them more human
                    raw_name = auth_result.get("data", {}).get("name", "")
                    if raw_name and "Customer#" in raw_name:
                        c_match = re.search(r'#0*(\d+)', raw_name)
                        first_name = f"Customer {c_match.group(1)}" if c_match else raw_name
                    else:
                        first_name = raw_name.split()[0] if raw_name else "there"

                    history.append({
                        "role": "system",
                        "content": (
                            f"Authentication successful. The customer's name is '{first_name}'. "
                            f"IMPORTANT: Use the name '{first_name}' in your very next reply. "
                            f"Greet them warmly, e.g. 'Got it, thanks {first_name}! I can see your profile details on my screen. How can I help you today?' "
                            f"Do NOT invent a different name."
                        ),
                    })
                    history.append({
                        "role": "system",
                        "content": (
                            "REMINDER: Your next reply must be a natural spoken sentence. "
                            "Do NOT mention function names, JSON, or tool parameters. "
                            "Speak as if you are a human on a phone call."
                        ),
                    })
                    # Stream the greeting response
                    def _greeting_stream():
                        return client.chat.completions.create(
                            model=MODEL_NAME,
                            messages=history,
                            max_tokens=100,
                            stream=True,
                            temperature=0.0,
                        )
                    stream = await loop.run_in_executor(None, _greeting_stream)
                    full_response_content = ""
                    for chunk in stream:
                        content = chunk.choices[0].delta.content
                        if content:
                            full_response_content += content
                            yield f"data: {json.dumps({'text': content})}\n\n"
                    response_text = _sanitize_response(full_response_content or f"Hi {first_name}! How can I help you today?")
                    history.append({"role": "assistant", "content": response_text})
                    yield f"data: {json.dumps({'done': True, 'data': [auth_result.get('data', {})]})}\n\n"
                    return
                else:
                    # Auth failed — tell the LLM what happened and let it respond naturally
                    import json as _json
                    history.append({
                        "role": "system",
                        "content": (
                            f"Authentication failed: {auth_result.get('message', 'No account found.')} "
                            "Apologise naturally and ask the customer to try their number again."
                        ),
                    })
                    # Fall through to the normal LLM call below

            # ── First LLM call — offloaded to thread pool (Groq SDK is sync) ─────
            response = await loop.run_in_executor(
                None,
                lambda: _call_llm(messages=history, tools=TOOLS, tool_choice="auto", max_tokens=250)
            )
            message = response.choices[0].message

            # ── If the LLM wants to call a tool ─────────────────────────────────
            if message.tool_calls:
                # Convert the ChatCompletionMessage object to a dict to avoid AttributeError
                # when iterating history (Pydantic models don't have .get())
                history.append(message.model_dump(exclude_none=True))

                # Execute ALL tool calls in PARALLEL
                tool_tasks = []
                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments or "{}")
                    print(f"Tool called: {fn_name}({fn_args})")
                    tool_tasks.append(_execute_tool(fn_name, fn_args))
                
                tool_results = await asyncio.gather(*tool_tasks)

                for tool_call, tool_result in zip(message.tool_calls, tool_results):
                    history.append({
                        "role":         "tool",
                        "tool_call_id":  tool_call.id,
                        "content":      json.dumps(tool_result, default=str),
                    })

                # ── Post-tool guidance injections ───────────────────────────────
                for tool_call, tool_result in zip(message.tool_calls, tool_results):
                    fn_name = tool_call.function.name

                    # After successful auth: force a clean greeting, not tool narration
                    if fn_name == "authenticate_user" and tool_result.get("success"):
                        raw_customer_name = tool_result.get("data", {}).get("name", "")
                        if raw_customer_name and "Customer#" in raw_customer_name:
                            c_match = re.search(r'#0*(\d+)', raw_customer_name)
                            first_name = f"Customer {c_match.group(1)}" if c_match else raw_customer_name
                        else:
                            first_name = raw_customer_name.split()[0] if raw_customer_name else "there"
                        history.append({
                            "role": "system",
                            "content": (
                                f"Authentication succeeded. The customer's name is '{first_name}'. "
                                f"Greet them warmly and mention that their profile details are now visible. "
                                f"Ask 'How can I help you today?' Do NOT say any function name. Just greet naturally."
                            ),
                        })

                     # After get_order_details: explain result and STOP
                    if fn_name == "get_order_details":
                        data = tool_result.get("data", {})
                        products = data if isinstance(data, list) else [data]
                        
                        num_items = len(products)
                        if num_items == 1:
                            p = products[0]
                            product_summary = f"'{p.get('product_name')}'"
                            expired = p.get("expired", False)
                            resolution = p.get("recommended_resolution", "refund")
                        else:
                            names = [p.get("product_name") for p in products]
                            product_summary = f"{num_items} items (" + ", ".join([f"'{n}'" for n in names]) + ")"
                            expired = any(p.get("expired") for p in products)
                            resolution = products[0].get("recommended_resolution", "refund")

                        # Nuanced Intent Detection: Generic vs Specific
                        msg_lower = request.message.lower()
                        specific_problem_keywords = [
                            "refund", "return", "exchange", "broken", "wrong", 
                            "expired", "damaged", "defective", "stolen", "lost", "faulty"
                        ]
                        # User wants specific info
                        info_request_keywords = ["ship", "date", "status", "price", "amount", "tax", "discount", "where", "delivered", "receive"]
                        
                        has_problem = any(kw in msg_lower for kw in specific_problem_keywords)
                        has_info_request = any(kw in msg_lower for kw in info_request_keywords)
                        asked_about_expiry = "expire" in msg_lower or "old" in msg_lower

                        if not (has_problem or has_info_request or asked_about_expiry):
                            # User just provided ID, hasn't asked for anything yet
                            instruction = (
                                f"I have found order details for {product_summary}. "
                                f"CRITICAL: Do NOT show ANY details yet (no dates, no prices, no expiration). "
                                f"Acknowledge the order and ask: "
                                f"'I've found your order for {product_summary if num_items == 1 else str(num_items) + ' items'}. "
                                f"What specific information would you like to know about it? "
                                f"I can check on the status, shipping dates, pricing, or any other details.'"
                            )
                        elif has_info_request and not (has_problem or asked_about_expiry):
                            # User asked for specific info (e.g., "when was it shipped?")
                            instruction = (
                                f"The user wants to know specific info: '{request.message}'. "
                                f"Provide ONLY the information they asked for based on the tool results. "
                                f"Do NOT mention expiration, refunds, or other unrelated details unless they specifically asked."
                            )
                        elif has_problem or asked_about_expiry:
                            # User has a problem or asked about expiration
                            if expired:
                                if resolution == "reject":
                                    instruction = (
                                        f"The user has a problem/query and the item is older than 90 days. "
                                        f"Politely explain that it is outside the return window. "
                                        f"Do NOT offer a refund or exchange."
                                    )
                                else:
                                    instruction = (
                                        f"The user has a problem/query and the item is old (expired). "
                                        f"Suggest a {resolution} as the policy allows."
                                    )
                            else:
                                instruction = (
                                    f"The user has a problem but the items are within the valid return window. "
                                    f"Help them with their specific issue."
                                )

                        history.append({"role": "system", "content": instruction})

                # General reminder: never narrate tool calls in your reply
                history.append({
                    "role": "system",
                    "content": (
                        "REMINDER: Your next reply must be a natural spoken sentence. "
                        "Do NOT mention function names, JSON, or tool parameters. "
                        "Speak as if you are a human on a phone call."
                    ),
                })

                # ── Second LLM call — Streaming ──────────────────────────────────
                def _sync_stream():
                    return client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=history,
                        max_tokens=250,
                        stream=True,
                        temperature=0.0,
                    )

                stream = await loop.run_in_executor(None, _sync_stream)

                full_response_content = ""
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        full_response_content += content
                        yield f"data: {json.dumps({'text': content})}\n\n"

                response_text = _sanitize_response(full_response_content or "I've taken care of that for you.")
                history.append({"role": "assistant", "content": response_text})

                # Collect all data from tool results (non-empty)
                all_data = []
                for r in tool_results:
                    d = r.get("data", {})
                    if isinstance(d, list):
                        all_data.extend(d)
                    elif d:
                        all_data.append(d)

                # Send finalize event with all data cards
                def _json_serial(obj):
                    """JSON serializer for objects not serializable by default json code"""
                    if isinstance(obj, (_dt.datetime, _dt.date)):
                        return obj.isoformat()
                    from decimal import Decimal
                    if isinstance(obj, Decimal):
                        return float(obj)
                    if isinstance(obj, set):
                        return list(obj)
                    return str(obj)

                import datetime as _dt
                yield f"data: {json.dumps({'done': True, 'data': all_data}, default=_json_serial)}\n\n"

            else:
                # ── No tool call — plain conversational reply — Streaming ───────────
                def _sync_stream():
                    return client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=history,
                        max_tokens=250,
                        stream=True,
                        temperature=0.0,
                    )

                stream = await loop.run_in_executor(None, _sync_stream)

                full_response_content = ""
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        full_response_content += content
                        yield f"data: {json.dumps({'text': content})}\n\n"

                response_text = _sanitize_response(full_response_content or "")
                history.append({"role": "assistant", "content": response_text})
                yield f"data: {json.dumps({'done': True, 'data': []})}\n\n"

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"LLM Error Traceback:\n{tb}")
            error_str = str(e)

            if "429" in error_str or "rate" in error_str.lower():
                msg = "I'm receiving too many requests right now. Could you try again in a moment?"
            elif "504" in error_str or "timeout" in error_str.lower():
                msg = "The request timed out. Please try again."
            elif "503" in error_str or "unavailable" in error_str.lower():
                msg = "The AI service is briefly unavailable. Please try again shortly."
            else:
                msg = f"I'm having a little trouble: {tb[-300:]}"

            yield f"data: {json.dumps({'text': msg, 'done': True, 'data': []})}\n\n"

    if not client:
        raise HTTPException(status_code=500, detail="Groq API Key not configured.")

    import asyncio
    loop = asyncio.get_event_loop()

    # --- Session Reset / Truncation Logic ---
    clean_msg = request.message.lower().strip().replace("!", "").replace(".", "")
    is_greeting = clean_msg in ["hello", "hi", "hey", "start over", "restart"]
    
    # If it's a fresh greeting and we aren't halfway through a multi-turn tool call, reset
    if is_greeting and len(history) > 1:
        print(f"[SESSION] Resetting session {session_id} due to fresh greeting.")
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        SESSIONS[session_id] = history

    history.append({"role": "user", "content": request.message})
    
    # Limit history to prevent context bloat (last 15 turns)
    if len(history) > 30: # 15 user + 15 assistant messages
         # Keep system prompt at [0]
         SESSIONS[session_id] = [history[0]] + history[-20:]
         history = SESSIONS[session_id]
    return StreamingResponse(
        _stream_response(),
        media_type="text/event-stream"
    )
