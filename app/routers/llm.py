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
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.connectors.unified_connector import UnifiedConnector, ConfigurationError

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

# ── Tool definitions (12 tools — one per UnifiedConnector method) ──────────────

TOOLS = [
    # ── CRM / Salesforce ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "authenticate_user",
            "description": (
                "Verify a caller's identity using their customer ID. "
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
    # get_customer_orders and get_customer_profile removed for scope reduction
    {
        "type": "function",
        "function": {
            "name": "check_expiry",
            "description": (
                "Fetch details for a specific order to check for product expiry. "
                "Automatically determines if a product is expired and the recommended resolution. "
                "CRITICAL: You must call this ONLY after the user provides an order ID. "
                "NEVER invent or hallucinate an order ID."
            ),
            "parameters": {
                "type": "object",
                "required": ["customer_id", "order_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                    "order_id": {
                        "type": "string",
                        "description": "The Salesforce Order ID provided by the customer."
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
                "required": ["ticket_id"],
                "properties": {
                    "ticket_id":   {"type": "string"},
                    "customer_id": {"type": "string"}
                }
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

SYSTEM_PROMPT = """You are Aria — a real, warm, and caring customer service person. You are NOT a bot and you should never sound like one. You speak the way a friendly, competent human would on a phone call: naturally, with genuine empathy, and always calm. You use short sentences. You breathe between thoughts. You care.

You naturally say things like:
- "Of course!" / "Absolutely!" / "Sure thing!" / "Oh no, let me sort that out for you."
- "Let me just pull that up..." / "Give me one second..." / "Right, I'm on it."
- "That's totally understandable." / "I completely get that, I'm really sorry."
- "Great news!" / "Perfect!" / "All sorted!"

## YOUR RULES
1. **Authenticate first.** Call `authenticate_user` as soon as the customer gives their number. Don't do anything else until authentication succeeds.
2. **Let them lead.** After greeting, ask "How can I help you today?" and listen. Don't assume.
3. **Ask one thing at a time.** Only ask for what you're missing. Never ask for info you already have.
4. **Trust the tool results.** They calculate everything — expiry, ETAs, resolution type. Just read and relay them.
5. **Keep it short and human.** 1–2 spoken sentences max. No lists, no tables, no raw IDs, no field names. Pretend you're on a call.
6. **Match their language.** English by default. If they use Hindi, switch to Hindi naturally.
7. **Never mention your tools.** Don't say "check_expiry" or "authenticate_user" or any function name. The customer can't see that.
8. **Confirm before you act.** For refunds and exchanges: explain what you found, then ask "Shall I go ahead?" — and WAIT. Only run the action after a clear yes.
9. **Never make up data.** If you don't have an order ID, ticket ID, or anything else — ask. Don't invent.

---

## HOW TO HANDLE EACH SITUATION

### Starting the call
Say: *"Hi there! This is Aria — thanks for getting in touch. Could I just grab your customer number to get started?"*
- Map the number to CUST-00X format: 'one'→CUST-001, 'two'→CUST-002, 'three'→CUST-003, 'four'→CUST-004, 'five'→CUST-005
- If auth fails: *"Hmm, I couldn't find anything with that number — could you try once more?"*
- If auth succeeds: *"Lovely, hi [first name]! What can I do for you today?"*

### Support / Ticket (issue, problem, outage, ticket)
Say: *"Oh I'm sorry to hear that — let me help. Have you raised a ticket for this before, or is it a new issue?"*

**Have a ticket:**
- *"Sure, what's the ticket number?"*
- Call `check_ticket_status`. Normalization: "one" → "TICK-1001"
- Reply with status + ETA in one warm sentence.
- If they're upset: *"I completely understand — let me escalate this right now."*

**New issue:**
- *"Of course, I'll get that logged. Could you just describe what's happening?"*
- Call `raise_support_ticket`.
- *"Done! I've raised a ticket for you — our team will be in touch very soon."*

### Expired / Damaged product (order, product, delivery, damaged, expired)
Say: *"Oh no, I'm so sorry about that! What's your order number and I'll take a look right away?"*
- WAIT for the number. Never guess it.
- Call `check_expiry` using the order number the customer gave and their customer_id from authentication.
  - Normalise: "one zero zero one" → ORD-1001
- The post-tool system message will tell you exactly what to say next. Follow it precisely.
- Never call `initiate_refund` or `initiate_exchange` until the customer says yes.
- After confirmation: *"Perfect — all sorted! You'll get a confirmation very soon."*

### Anything else
Say: *"Oh, I'm set up just for product returns and support tickets right now — I'm sorry I can't help with that directly. Want me to get someone from the team to reach out?"*

---

## WORDS ARIA NEVER USES
- Never say: "null", "undefined", "API", raw field names, order/ticket IDs out loud, "Please provide your..."
- Never say: "I found X records", "The tool returned...", "check_expiry", "authenticate_user"
- Never sound stiff, formal or robotic. Never say "I am processing your request."

## ARIA'S VOICE — EXAMPLES
| Stiff (bad) | Natural (good) |
|---|---|
| "Please provide your customer ID." | "Could I just grab your customer number?" |
| "Authentication was successful." | "Great — hi [name], lovely to meet you!" |
| "I have initiated a refund." | "All sorted! Your refund's on its way." |
| "Your ticket has high priority." | "Good news — it's been flagged as high priority, so the team should have it sorted within 3 days." |
| "I'm sorry, I cannot assist with that." | "Oh, I'm afraid that's a bit outside what I can do — but let me point you to the right person!" |
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
    "authenticate_user", "check_expiry", "initiate_refund",
    "initiate_exchange", "check_ticket_status",
    "raise_support_ticket", "escalate_ticket"
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
    # Normalise IDs (LLM sometimes says 'ORDER-1001' or 'SALES-1001' instead of 'ORD-1001')
    import re
    if "order_id" in function_args:
        oid = str(function_args["order_id"]).upper()
        # Match digits
        match = re.search(r'(\d+)', oid)
        if match:
            # Reformat to ORD-XXXX (always use ORD prefix)
            function_args["order_id"] = f"ORD-{match.group(1)}"
    if "customer_id" in function_args:
        cid = str(function_args["customer_id"]).upper()
        match = re.search(r'(\d+)', cid)
        if match:
            # Reformat to CUST-XXX (padded to 3 digits)
            function_args["customer_id"] = f"CUST-{int(match.group(1)):03d}"
    if "ticket_id" in function_args:
        tid = str(function_args["ticket_id"]).upper()
        match = re.search(r'(\d+)', tid)
        if match:
            function_args["ticket_id"] = f"TICK-{match.group(1)}"

    uc = UnifiedConnector()
    dispatch = {
        # CRM
        "authenticate_user":       uc.authenticate_user,
        "check_expiry":            uc.get_order_details,
        "initiate_refund":         uc.initiate_refund,
        "initiate_exchange":       uc.initiate_exchange,
        # Support
        "check_ticket_status":     uc.check_ticket_status,
        "raise_support_ticket":    uc.raise_support_ticket,
        "escalate_ticket":         uc.escalate_ticket,
    }
    fn = dispatch.get(function_name)
    if fn is None:
        return {"success": False, "data": {}, "message": f"Unknown tool: {function_name}"}
    try:
        return await fn(**function_args)
    except ConfigurationError as ce:
        return {"success": False, "data": {}, "message": str(ce)}
    except TypeError as te:
        return {"success": False, "data": {}, "message": f"Tool call error: {te}"}

# ── TTS endpoint ───────────────────────────────────────────────────────────────

@router.post("/tts")
async def text_to_speech(request: TTSRequest):
    """Generate audio from text using edge-tts and return as a stream."""
    print(f"TTS Request: {request.text[:60]}...")
    try:
        clean_text = request.text.replace("_", " ")
        is_hindi = any("\u0900" <= c <= "\u097F" for c in clean_text)
        voice = "hi-IN-SwaraNeural" if is_hindi else "en-US-JennyNeural"
        communicate = edge_tts.Communicate(clean_text, voice, rate="+15%")
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
    async def _stream_response():
        try:
            # ── First LLM call — offloaded to thread pool (Groq SDK is sync) ─────
            response = await loop.run_in_executor(
                None,
                lambda: _call_llm(messages=history, tools=TOOLS, tool_choice="auto", max_tokens=250)
            )
            message = response.choices[0].message

            # ── If the LLM wants to call a tool ─────────────────────────────────
            if message.tool_calls:
                history.append(message)

                # Execute ALL tool calls
                tool_results = []
                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments or "{}")
                    print(f"Tool called: {fn_name}({fn_args})")

                    tool_result = await _execute_tool(fn_name, fn_args)
                    tool_results.append(tool_result)

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
                        customer_name = tool_result.get("data", {}).get("name", "")
                        first_name = customer_name.split()[0] if customer_name else "there"
                        history.append({
                            "role": "system",
                            "content": (
                                f"Authentication succeeded. The customer's name is {first_name}. "
                                f"Greet them by first name warmly and ask 'How can I help you today?' "
                                f"Do NOT say 'authenticating' or any function name. Just greet naturally."
                            ),
                        })

                    # After check_expiry: explain result and STOP — do NOT call initiate_refund/exchange yet
                    if fn_name == "check_expiry":
                        data = tool_result.get("data", {})
                        products = data if isinstance(data, list) else [data]
                        p = products[0] if products else {}
                        product_name = p.get("product_name") or p.get("name", "the product")
                        category     = p.get("category", "")
                        expired      = p.get("expired", False)
                        resolution   = p.get("recommended_resolution", "refund")

                        if expired:
                            if resolution == "exchange":
                                instruction = (
                                    f"The tool confirmed that '{product_name}' (category: {category}) HAS expired. "
                                    f"The recommended resolution is an EXCHANGE (replacement unit). "
                                    f"Tell the customer what you found in 1 warm sentence and ask: "
                                    f"'Shall I go ahead and arrange a replacement for you?' "
                                    f"STOP HERE. Do NOT call initiate_exchange or initiate_refund yet. "
                                    f"Wait for the customer to say yes or no."
                                )
                            else:
                                instruction = (
                                    f"The tool confirmed that '{product_name}' (category: {category}) HAS expired. "
                                    f"The recommended resolution is a REFUND. "
                                    f"Tell the customer what you found in 1 warm sentence and ask: "
                                    f"'Shall I go ahead and arrange a full refund for you?' "
                                    f"STOP HERE. Do NOT call initiate_refund yet. "
                                    f"Wait for the customer to say yes or no."
                                )
                        else:
                            instruction = (
                                f"The tool confirmed that '{product_name}' has NOT expired. "
                                f"Tell the customer the good news in 1 warm sentence and ask if there is "
                                f"anything else you can help with. DO NOT offer a refund or exchange."
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
                yield f"data: {json.dumps({'done': True, 'data': all_data})}\n\n"

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
            error_str = str(e)
            print(f"LLM Error: {error_str}")

            if "429" in error_str or "rate" in error_str.lower():
                msg = "I'm receiving too many requests right now. Could you try again in a moment?"
            elif "504" in error_str or "timeout" in error_str.lower():
                msg = "The request timed out. Please try again."
            elif "503" in error_str or "unavailable" in error_str.lower():
                msg = "The AI service is briefly unavailable. Please try again shortly."
            else:
                msg = "I'm having a little trouble right now. Could you please try again?"

            yield f"data: {json.dumps({'text': msg, 'done': True, 'data': []})}\n\n"

    if not client:
        raise HTTPException(status_code=500, detail="Groq API Key not configured.")

    import asyncio
    loop = asyncio.get_event_loop()

    session_id = request.session_id
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    history = SESSIONS[session_id]
    history.append({"role": "user", "content": request.message})
    return StreamingResponse(
        _stream_response(),
        media_type="text/event-stream"
    )
