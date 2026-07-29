# Context — `apps/chatbot/`

## Purpose

The `chatbot` app serves as the agentic reasoning layer of the platform. It wraps the Groq LLM API and provides a natural-language interface for anonymous patients to find open slots, book, reschedule, or cancel appointments.

## Key Models (`models.py`)

- `ConversationSession`: Represents a continuous session for an anonymous user. Identified via a client-provided `session_key` (UUID). It stores temporary conversational state like `intent`, `pending_slot`, and `user_email` once collected.
- `Message`: Stores the conversation history (User, Assistant, System, and Tool calls).

## Key Endpoints (`/api/chatbot/`)

- `POST /sessions/` (`StartSessionView`) — Initializes a new session and returns a `session_key` UUID.
- `POST /message/` (`SendMessageView`) — The core loop trigger. Accepts a user message, passes it to the agent, executes tools if requested, and returns the LLM's response.
- `GET /sessions/<uuid:session_key>/messages/` (`SessionHistoryView`) — Returns the chat history excluding internal tool calls for clean UI rendering.
- `DELETE /sessions/<uuid:session_key>/` (`DeleteSessionView`) — Cleans up a session.

## Design Decisions

- **Agentic Loop** (`chatbot/agent.py`): The conversation runs in a loop inside the `SendMessageView` request. If the LLM requests a tool call (e.g., `get_available_slots` or `book_appointment`), the `ToolExecutor` fires the corresponding service from `calendar_app`, feeds the result back to the LLM, and allows the LLM to generate the final human-readable response.
- **Strict Email Enforcement**: The LLM is heavily prompted to collect the user's email address via the `save_session_email` tool before invoking any booking-related tools, acting as a lightweight authorization mechanism.
- **Dynamic System Prompts**: The prompt injected into the session at runtime contains live data (Current Timezone, Date, Provider Name, Provider Working Hours) fetched dynamically from `ProviderSettings` to ensure accurate reasoning.
