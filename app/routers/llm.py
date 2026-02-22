import json
import re
from openai import OpenAI
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from app.config import settings
from app.connectors.student_connector import StudentConnector
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector

# Initialize Router
router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    responses={404: {"description": "Not found"}},
)

# Initialize Groq Client (OpenAI-compatible API)
api_key = settings.GROQ_API_KEY
if api_key:
    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        timeout=20.0,
    )
else:
    client = None

# Small, fast model on Groq with native tool calling support
MODEL_NAME = "llama-3.1-8b-instant"

# ── Tool definitions (OpenAI tool-calling format — Groq supports this natively) ──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_student_data",
            "description": "Fetch student course data based on filters like batch, course, term, marks, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "batch": {
                        "type": "string",
                        "description": "Student batch code (e.g., '22f2', '21f3'). Case insensitive."
                    },
                    "course_code": {
                        "type": "string",
                        "description": "Course code (e.g., 'CS2003P'). Case insensitive."
                    },
                    "course_name": {
                        "type": "string",
                        "description": "Course name (e.g., 'Business Data Management'). Partial match supported."
                    },
                    "term": {
                        "type": "string",
                        "description": "Term code (e.g., 'F1-2024'). Case insensitive."
                    },
                    "min_marks": {
                        "type": "integer",
                        "description": "Minimum marks to filter by."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return. Default to 5."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_crm_data",
            "description": "Fetch CRM customer data including customer names, emails, companies, status, and revenue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return. Default to 5."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_support_data",
            "description": "Fetch support ticket data including ticket IDs, subjects, status, priority, and customer info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return. Default to 5."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_analytics_data",
            "description": "Fetch analytics/metrics data including page views, sessions, conversions, bounce rates, and revenue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return. Default to 5."
                    }
                }
            }
        }
    },
]

SYSTEM_PROMPT = (
    "You are a helpful assistant for a Universal Data Connector system. "
    "You have access to four data sources: students, CRM, support tickets, and analytics. "
    "Based on the user's question, choose the most appropriate data source tool: "
    "- Use `get_student_data` for questions about students, courses, marks, batches, terms, grades. "
    "- Use `get_crm_data` for questions about customers, CRM, sales, companies, revenue. "
    "- Use `get_support_data` for questions about support tickets, issues, complaints, priorities. "
    "- Use `get_analytics_data` for questions about analytics, metrics, page views, sessions, conversions. "
    "Always try to use the most relevant tool. If the request is ambiguous, pick the best match. "
    "Do not refuse to fetch data; always attempt to use a tool. "
    "If the user is in voice mode (provided in the request context), be extremely concise and conversational. "
    "Avoid long tables or lists; instead, summarize the key highlights verbally."
)

# In-memory session storage (OpenAI message format)
SESSIONS: Dict[str, list] = {}

# Define User Input Model
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    voice_mode: bool = False


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
def chat_with_data(request: ChatRequest):
    if not client:
        raise HTTPException(status_code=500, detail="Groq API Key not configured. Set GROQ_API_KEY in .env")

    session_id = request.session_id

    # Initialize history with system prompt
    if session_id not in SESSIONS:
        SESSIONS[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    history = SESSIONS[session_id]

    try:
        # Append user message
        history.append({"role": "user", "content": request.message})

        # 1. First call — may return a tool call (Groq supports native tool calling)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=history,
            tools=TOOLS,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # 2. Check for tool call
        if message.tool_calls:
            # Append the assistant's tool-call message to history
            history.append(message)

            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments or "{}")

            print(f"Tool called: {function_name} with args: {function_args}")

            # 3. Execute the tool
            data_response = _execute_tool(function_name, function_args)

            # 4. Append tool result to history
            history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps({"result": data_response}, default=str),
            })

            # 5. Get final natural language response
            final_response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=history,
                tools=TOOLS,
            )

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
            reason = "API rate limit reached. Please wait a moment and retry."
        elif '503' in error_str or 'unavailable' in error_str.lower():
            reason = "AI service temporarily unavailable."
        elif '504' in error_str or 'timeout' in error_str.lower():
            reason = "AI service timed out."
        elif 'auth' in error_str.lower() or '401' in error_str or '403' in error_str:
            reason = "API key issue — please check your GROQ_API_KEY."
        else:
            reason = "AI service error."

        if is_crm:
            connector = CRMConnector()
            data = connector.fetch(limit=limit)
            return {
                "response": f"I'm running in offline mode ({reason}). Here are {len(data)} CRM customer records.",
                "data": data
            }
        elif is_support:
            connector = SupportConnector()
            data = connector.fetch(limit=limit)
            return {
                "response": f"I'm running in offline mode ({reason}). Here are {len(data)} support tickets.",
                "data": data
            }
        elif is_analytics:
            connector = AnalyticsConnector()
            data = connector.fetch(limit=limit)
            return {
                "response": f"I'm running in offline mode ({reason}). Here are {len(data)} analytics records.",
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
                "response": f"I'm running in offline mode ({reason}). I found {len(data)} student results based on your keywords.",
                "data": data
            }
