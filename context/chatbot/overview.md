# Chatbot App Overview

> **Namespace:** `apps.chatbot`
> **Purpose:** Manages Groq conversation sessions, message history, and the agentic tool-calling loop.

---

## 1. Core Responsibilities

The `chatbot` app acts as the AI-driven natural language interface for the booking system. It implements a fully autonomous "Agentic Loop" connecting the external LLM (Groq) with the internal system capabilities (via tool calling), allowing users to request complex scheduling operations entirely via chat.

---

## 2. Models

### `ConversationSession`
Represents an ongoing chat thread linked to a specific user.

```python
class ConversationSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `Message`
A single utterance in a conversation thread.

```python
class Message(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
        ("tool", "Tool"),
    ]
    session = models.ForeignKey(ConversationSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    tool_call_id = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True) # Tool name
    timestamp = models.DateTimeField(auto_now_add=True)
```

---

## 3. Tool Calling & Agentic Loop (`agent.py` & `tools.py`)

### The System Prompt Context Injection
Every time a message is sent, a dynamic system prompt is built, injecting real-time data from `apps.calendar_app.ProviderSettings` so the LLM knows the current time and the admin's working hours.

```python
# snippet from agent.py
system_prompt = f"""You are a helpful scheduling assistant for {ps.provider_name}.
Current date and time: {timezone.now().astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')} ({ps.timezone}).
Bookable hours are: {work_days_str}, from {ps.work_start.strftime('%H:%M')} to {ps.work_end.strftime('%H:%M')}, in {ps.slot_duration}-minute slots.
You are speaking with: {user.get_full_name() or user.username}.
Always confirm appointment details with the user before booking, rescheduling, or cancelling."""
```

### Available Tools (`tools.py`)
The LLM is provided with a JSON schema defining 5 distinct tools it can use:

1. **`get_available_slots`**: Queries `calendar_app` availability.
2. **`book_appointment`**: Commits a booking to the calendar.
3. **`reschedule_appointment`**: Modifies an existing booking.
4. **`cancel_appointment`**: Deletes an existing booking.
5. **`list_my_appointments`**: Retrieves user's `Booking` references.

Example Schema (`book_appointment`):
```json
{
    "type": "function",
    "function": {
        "name": "book_appointment",
        "description": "Book a slot on the admin's calendar for the current user. ALWAYS obtain explicit user confirmation before calling this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_time": {"type": "string", "description": "ISO format start time"},
                "end_time": {"type": "string", "description": "ISO format end time"},
                "reason": {"type": "string", "description": "Reason for booking"}
            },
            "required": ["start_time", "end_time"]
        }
    }
}
```

### The Execution Flow
1. Fetch the last 10 messages from DB to maintain context without exceeding token limits.
2. Pass System Prompt + Context + User Message + Tool Schemas to Groq `chat.completions.create`.
3. If Groq returns a `tool_calls` array, intercept it.
4. Execute `tools.execute_tool(tool_name, arguments)` internally, which routes to `calendar_app` views or direct database queries.
5. Append the result as a new `tool` role message and recursively call Groq again to synthesize the final natural language answer.

---

## 4. Endpoints & Views

The chatbot is public/anonymous. Sessions are isolated using standard UUID session keys.
All responses are wrapped in `ApiResponse`.

| Endpoint | Method | Payload / Action |
|----------|--------|------------------|
| `/api/v1/chat/sessions/` | `POST` | Generates a new `ConversationSession`. Returns `session_key`. Payload: `{"provider_id": 1}` |
| `/api/v1/chat/sessions/<id>/messages/` | `GET` | Retrieves full history for a session, filtering out internal `tool` messages. |
| `/api/v1/chat/sessions/<id>/` | `DELETE` | Deletes a session entirely. |
| `/api/v1/chat/message/` | `POST` | Payload: `{"session_key": "...", "message": "Hi"}`. Triggers the Agentic Loop. |

---

## 5. Services

Business logic is encapsulated in dedicated service classes:
- **`ChatSessionService`**: Manages session creation, retrieval, and deletion.
- **`AgenticService`**: Wraps the agentic loop execution and properly handles application errors.
