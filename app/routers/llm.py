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
    "You are a helpful and conversational assistant for a Universal Data Connector. "
    "You have access to tools for fetching data from: students, CRM, support tickets, and analytics. "
    "TOOL USE RULES: "
    "1. ONLY use a tool if the user explicitly asks for information related to those datasets. "
    "2. If the user is just greeting you (e.g., 'Hello', 'Hi'), checking if you are there, or asking if they are audible (e.g., 'Am I audible?', 'Can you hear me?'), DO NOT use any tools. Just respond naturally and conversationally. "
    "3. Do NOT make up information or fetch data if the query is unrelated to your four data sources. "
    "VOICE MODE PERSONA: "
    "If `voice_mode` is enabled, speak naturally like a human colleague. "
    "- Do NOT use technical jargon like 'records', 'database', or 'limit'. "
    "- Use warm transitions: 'Sure, let me check that for you...', 'I found the details in the CRM'. "
    "- Be concise and summarized. Avoid robotic lists. "
    "LANGUAGE MATCHING (STRICT): "
    "Always respond in the same language the user is using. "
    "Default to English, but switch to Hindi immediately if the user speaks Hindi. "
    "Switch back to English as soon as the user speaks English again."
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
