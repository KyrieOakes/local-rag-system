"""
Server-side conversation memory and prompt-budget management.

This module is the single source of truth for context handling:
- restores persisted memory from SQLite by conversation_id;
- reconciles it with client-side messages that may not be persisted yet;
- keeps a schema-versioned rolling summary plus complete recent turns;
- enforces both turn-count and token ceilings for short-term memory;
- uses a tokenizer-based budget for routing and answer-generation prompts;
- budgets system instructions, question, history, documents, safety margin,
  and reserved output tokens as one context window.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import tiktoken
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.llm.local_llm import get_llm
from app.rag.conversation_store import ConversationStore, get_conversation_store
from app.rag.prompt import RAG_SYSTEM_PROMPT
from app.schemas.rag import Message

logger = logging.getLogger(__name__)

_summary_lock = threading.Lock()
SUMMARY_SCHEMA_VERSION = 1
SUMMARY_LIST_FIELDS = ("goals", "constraints", "decisions", "open_questions")


class ContextWindowExceededError(ValueError):
    """Raised when the current question alone cannot fit the configured window."""


@dataclass(frozen=True)
class ConversationMemory:
    """Long-term summary plus recent verbatim conversation messages."""

    summary: str
    messages: list[Message]
    source: str
    summary_revision: int = 0
    summary_token_count: int = 0


@dataclass(frozen=True)
class ConversationTurn:
    """One complete user + assistant exchange selected atomically."""

    messages: tuple[Message, Message]
    message_ids: tuple[int | None, int | None]
    turn_id: str | None = None


@dataclass(frozen=True)
class PreparedMemory:
    """A token-budgeted view of conversation memory."""

    summary: str
    pending_messages: list[Message]
    messages: list[Message]
    token_count: int
    dropped_messages: int
    included_turns: int
    dropped_turns: int
    summary_tokens: int
    pending_tokens: int
    recent_tokens: int
    included_pending_turns: int
    dropped_pending_turns: int


@dataclass(frozen=True)
class GenerationContext:
    """Fully budgeted inputs for the final RAG generation call."""

    summary: str
    pending_history: list[Message]
    history: list[Message]
    documents: list[Document]
    included_document_count: int
    input_tokens: int
    history_tokens: int
    document_tokens: int
    dropped_history_messages: int
    dropped_documents: int
    included_history_turns: int
    dropped_history_turns: int
    summary_tokens: int
    summary_revision: int
    pending_history_tokens: int
    included_pending_turns: int
    dropped_pending_turns: int


class CompactionStatus(str, Enum):
    COMPACTED = "compacted"
    NOT_NEEDED = "not_needed"
    RETRYABLE_FAILURE = "retryable_failure"
    STALE = "stale"
    CONVERSATION_DELETED = "conversation_deleted"


@dataclass(frozen=True)
class CompactionOutcome:
    status: CompactionStatus
    through_message_id: int | None = None
    compacted_turns: int = 0
    summary_revision: int = 0
    summary_tokens: int = 0
    error_code: str | None = None
    needs_follow_up: bool = False


@lru_cache(maxsize=4)
def _get_encoding(name: str):
    if name == "offline_multilingual":
        return None
    try:
        return tiktoken.get_encoding(name)
    except Exception as exc:
        logger.warning(
            "Tokenizer encoding '%s' is unavailable; using conservative multilingual "
            "offline counting: %s",
            name,
            exc,
        )
        return None


def _count_tokens_offline(text: str) -> int:
    """
    Conservative multilingual fallback when a BPE table is unavailable.

    CJK and non-ASCII characters count individually; ASCII word runs use a
    conservative 3 chars/token ratio; punctuation counts individually.
    Unlike the old global len/3 heuristic, this does not undercount Chinese.
    """
    count = 0
    for piece in re.findall(r"[A-Za-z0-9_]+|\s+|[^\w\s]|[^\x00-\x7F]", text):
        if piece.isspace():
            count += max(1, (len(piece) + 7) // 8)
        elif piece.isascii() and (piece[0].isalnum() or piece[0] == "_"):
            count += max(1, (len(piece) + 2) // 3)
        else:
            count += len(piece)
    return count


def count_tokens(text: str) -> int:
    """Count tokens with the configured deterministic tokenizer."""
    if not text:
        return 0
    encoding = _get_encoding(settings.context_tokenizer_encoding)
    if encoding is None:
        return _count_tokens_offline(text)
    return len(encoding.encode(text, disallowed_special=()))


def _prefix_within_budget(text: str, max_tokens: int) -> str:
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if count_tokens(text[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _suffix_within_budget(text: str, max_tokens: int) -> str:
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if count_tokens(text[len(text) - middle:]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return text[len(text) - low:] if low else ""


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Keep the beginning and end of oversized text within max_tokens."""
    if not text or max_tokens <= 0:
        return ""

    encoding = _get_encoding(settings.context_tokenizer_encoding)
    if encoding is None:
        if count_tokens(text) <= max_tokens:
            return text
        marker = "\n...[content truncated to fit context window]...\n"
        marker_tokens = count_tokens(marker)
        if max_tokens <= marker_tokens + 2:
            return _prefix_within_budget(text, max_tokens)
        content_budget = max_tokens - marker_tokens
        head_budget = max(1, content_budget * 2 // 3)
        tail_budget = max(1, content_budget - head_budget)
        return (
            _prefix_within_budget(text, head_budget)
            + marker
            + _suffix_within_budget(text, tail_budget)
        )

    tokens = encoding.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return text

    marker = "\n...[content truncated to fit context window]...\n"
    marker_tokens = encoding.encode(marker, disallowed_special=())
    if max_tokens <= len(marker_tokens) + 2:
        return encoding.decode(tokens[:max_tokens])

    content_budget = max_tokens - len(marker_tokens)
    head_count = max(1, content_budget * 2 // 3)
    tail_count = max(1, content_budget - head_count)
    return (
        encoding.decode(tokens[:head_count])
        + marker
        + encoding.decode(tokens[-tail_count:])
    )


def parse_structured_summary(raw: str) -> dict | None:
    """Validate model output and return the canonical v1 summary payload."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        return None

    overview = payload.get("summary", "")
    entities = payload.get("entities", {})
    if not isinstance(overview, str) or not isinstance(entities, dict):
        return None

    normalized: dict = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "summary": overview.strip(),
    }
    for field in SUMMARY_LIST_FIELDS:
        values = payload.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return None
        normalized[field] = [value.strip() for value in values if value.strip()]

    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in entities.items()
    ):
        return None
    normalized["entities"] = {
        key.strip(): value.strip()
        for key, value in entities.items()
        if key.strip() and value.strip()
    }
    if not any(
        normalized.get(field)
        for field in ("summary", *SUMMARY_LIST_FIELDS, "entities")
    ):
        return None
    return normalized


def serialize_structured_summary(payload: dict) -> str:
    """Use deterministic JSON so revisions and token metrics are reproducible."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def render_stored_summary(raw: str) -> str:
    """Render structured JSON for prompts; preserve legacy plain-text summaries."""
    payload = parse_structured_summary(raw)
    if payload is None:
        return (raw or "").strip()

    sections = []
    if payload["summary"]:
        sections.append(f"Overview: {payload['summary']}")
    labels = {
        "goals": "Goals",
        "constraints": "Constraints",
        "decisions": "Decisions",
        "open_questions": "Open questions",
    }
    for field in SUMMARY_LIST_FIELDS:
        values = payload[field]
        if values:
            sections.append(f"{labels[field]}:\n" + "\n".join(f"- {value}" for value in values))
    if payload["entities"]:
        sections.append(
            "Entities:\n"
            + "\n".join(
                f"- {key}: {value}" for key, value in payload["entities"].items()
            )
        )
    return "\n".join(sections)


def _as_message(raw) -> Message:
    if isinstance(raw, Message):
        return raw
    if isinstance(raw, dict):
        return Message(
            role=raw["role"],
            content=raw["content"],
            turn_id=raw.get("turn_id"),
        )
    return Message(
        role=raw.role,
        content=raw.content,
        turn_id=getattr(raw, "turn_id", None),
    )


def _raw_message_id(raw) -> int | None:
    value = raw.get("id") if isinstance(raw, dict) else getattr(raw, "id", None)
    return value if isinstance(value, int) else None


def _group_complete_turns(
    raw_messages: list,
    *,
    stop_at_incomplete: bool = False,
) -> list[ConversationTurn]:
    """Group adjacent messages without ever exposing half of a Q&A turn."""
    turns: list[ConversationTurn] = []
    index = 0
    while index < len(raw_messages):
        if index + 1 >= len(raw_messages):
            break
        user = _as_message(raw_messages[index])
        assistant = _as_message(raw_messages[index + 1])
        ids_match = (
            user.turn_id is None
            or assistant.turn_id is None
            or user.turn_id == assistant.turn_id
        )
        if user.role != "user" or assistant.role != "assistant" or not ids_match:
            if stop_at_incomplete:
                break
            index += 1
            continue
        turn_id = user.turn_id or assistant.turn_id
        turns.append(
            ConversationTurn(
                messages=(user, assistant),
                message_ids=(
                    _raw_message_id(raw_messages[index]),
                    _raw_message_id(raw_messages[index + 1]),
                ),
                turn_id=turn_id,
            )
        )
        index += 2
    return turns


def _message_key(message: Message) -> tuple[str, str]:
    return message.role, message.content


def _merge_histories(persisted: list[Message], client: list[Message]) -> list[Message]:
    """
    Merge a persisted history with a client tail.

    The client is useful during the short race where the previous response has
    reached the browser but its background SQLite write has not completed yet.
    Longest-overlap reconciliation prevents duplicate messages.
    """
    if not persisted:
        return client
    if not client:
        return persisted

    persisted_keys = [_message_key(message) for message in persisted]
    client_keys = [_message_key(message) for message in client]

    best_client_end = None
    best_overlap = 0
    for client_start in range(len(client_keys)):
        max_overlap = min(len(persisted_keys), len(client_keys) - client_start)
        for overlap in range(max_overlap, 0, -1):
            if persisted_keys[-overlap:] == client_keys[client_start:client_start + overlap]:
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_client_end = client_start + overlap
                break

    if best_client_end is None:
        logger.warning(
            "Client history did not overlap persisted history; using server-side memory only"
        )
        return persisted

    return persisted + client[best_client_end:]


def resolve_conversation_memory(
    conversation_id: str | None,
    client_history: list | None,
) -> ConversationMemory:
    """Restore server memory and reconcile any not-yet-persisted client tail."""
    client_messages = [_as_message(message) for message in (client_history or [])]
    if not conversation_id:
        return ConversationMemory(summary="", messages=client_messages, source="client")

    try:
        state = get_conversation_store().get_context_state(conversation_id)
    except Exception as exc:
        logger.warning(
            "Failed to restore conversation %s; using client history: %s",
            conversation_id,
            exc,
        )
        return ConversationMemory(summary="", messages=client_messages, source="client_fallback")

    if not state:
        return ConversationMemory(summary="", messages=client_messages, source="client")

    persisted = [_as_message(message) for message in state["messages"]]
    merged = _merge_histories(persisted, client_messages)
    rendered_summary = render_stored_summary(state.get("summary", ""))
    logger.info(
        "[CONTEXT] restored conversation=%s summary_revision=%d summary_tokens=%d "
        "persisted_messages=%d client_messages=%d merged_messages=%d",
        conversation_id,
        state.get("summary_revision", 0),
        count_tokens(rendered_summary),
        len(persisted),
        len(client_messages),
        len(merged),
    )
    return ConversationMemory(
        summary=rendered_summary,
        messages=merged,
        source="server",
        summary_revision=state.get("summary_revision", 0),
        summary_token_count=state.get("summary_token_count", 0),
    )


def _format_message(message: Message) -> str:
    role_label = "User" if message.role == "user" else "Assistant"
    return f"{role_label}: {message.content}"


def format_memory_for_prompt(
    summary: str,
    messages: list[Message],
    pending_messages: list[Message] | None = None,
) -> str:
    """Render structured summary, pending buffer, and recent turns."""
    sections = []
    if summary:
        sections.append(f"Earlier conversation summary:\n{summary}")
    if pending_messages:
        pending = "\n".join(_format_message(message) for message in pending_messages)
        sections.append(f"Pending compaction conversation:\n{pending}")
    if messages:
        recent = "\n".join(_format_message(message) for message in messages)
        sections.append(f"Recent conversation:\n{recent}")
    return "\n\n".join(sections)


def format_documents_for_context(documents: list[Document]) -> str:
    """Format retrieved documents with source headers."""
    formatted_chunks = []
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("source", "unknown")
        page = document.metadata.get("page")
        header = f"[Source {index}] source={source}"
        if page is not None:
            header += f", page={page}"
        formatted_chunks.append(f"{header}\n{document.page_content}")
    return "\n\n".join(formatted_chunks)


def _flatten_turns(turns: list[ConversationTurn]) -> list[Message]:
    return [message for turn in turns for message in turn.messages]


def _truncate_turn_to_budget(
    turn: ConversationTurn,
    summary: str,
    max_tokens: int,
    recent_max_tokens: int,
) -> list[Message]:
    """Keep both roles of an oversized newest turn while truncating its content."""
    empty_messages = [
        Message(role=message.role, content="", turn_id=message.turn_id)
        for message in turn.messages
    ]
    recent_fixed = count_tokens(format_memory_for_prompt("", empty_messages))
    total_fixed = count_tokens(format_memory_for_prompt(summary, empty_messages))
    content_budget = min(
        recent_max_tokens - recent_fixed,
        max_tokens - total_fixed,
    )
    if content_budget <= 0:
        return []

    original_tokens = [count_tokens(message.content) for message in turn.messages]
    original_total = sum(original_tokens)
    if original_total <= 0:
        return empty_messages

    for _attempt in range(4):
        first_budget = content_budget * original_tokens[0] // original_total
        second_budget = content_budget - first_budget
        if content_budget >= 2:
            if original_tokens[0] and first_budget == 0:
                first_budget, second_budget = 1, content_budget - 1
            if original_tokens[1] and second_budget == 0:
                first_budget, second_budget = content_budget - 1, 1
        candidate = [
            Message(
                role=turn.messages[0].role,
                content=truncate_to_tokens(turn.messages[0].content, first_budget),
                turn_id=turn.turn_id,
            ),
            Message(
                role=turn.messages[1].role,
                content=truncate_to_tokens(turn.messages[1].content, second_budget),
                turn_id=turn.turn_id,
            ),
        ]
        recent_tokens = count_tokens(format_memory_for_prompt("", candidate))
        total_tokens = count_tokens(format_memory_for_prompt(summary, candidate))
        if recent_tokens <= recent_max_tokens and total_tokens <= max_tokens:
            return candidate
        overflow = max(
            recent_tokens - recent_max_tokens,
            total_tokens - max_tokens,
            1,
        )
        content_budget -= overflow + 2
        if content_budget <= 0:
            break
    return []


def _truncate_pending_turn_to_budget(
    turn: ConversationTurn,
    summary: str,
    recent_messages: list[Message],
    max_tokens: int,
    pending_max_tokens: int,
) -> list[Message]:
    """Keep both roles of one oversized pending turn within its own section."""
    empty_messages = [
        Message(role=message.role, content="", turn_id=message.turn_id)
        for message in turn.messages
    ]
    pending_fixed = count_tokens(format_memory_for_prompt("", [], empty_messages))
    total_fixed = count_tokens(
        format_memory_for_prompt(summary, recent_messages, empty_messages)
    )
    content_budget = min(
        pending_max_tokens - pending_fixed,
        max_tokens - total_fixed,
    )
    if content_budget <= 0:
        return []

    original_tokens = [count_tokens(message.content) for message in turn.messages]
    original_total = sum(original_tokens)
    if original_total <= 0:
        return empty_messages

    for _attempt in range(4):
        first_budget = content_budget * original_tokens[0] // original_total
        second_budget = content_budget - first_budget
        if content_budget >= 2:
            if original_tokens[0] and first_budget == 0:
                first_budget, second_budget = 1, content_budget - 1
            if original_tokens[1] and second_budget == 0:
                first_budget, second_budget = content_budget - 1, 1
        candidate = [
            Message(
                role=turn.messages[0].role,
                content=truncate_to_tokens(turn.messages[0].content, first_budget),
                turn_id=turn.turn_id,
            ),
            Message(
                role=turn.messages[1].role,
                content=truncate_to_tokens(turn.messages[1].content, second_budget),
                turn_id=turn.turn_id,
            ),
        ]
        pending_tokens = count_tokens(format_memory_for_prompt("", [], candidate))
        total_tokens = count_tokens(
            format_memory_for_prompt(summary, recent_messages, candidate)
        )
        if pending_tokens <= pending_max_tokens and total_tokens <= max_tokens:
            return candidate
        overflow = max(
            pending_tokens - pending_max_tokens,
            total_tokens - max_tokens,
            1,
        )
        content_budget -= overflow + 2
        if content_budget <= 0:
            break
    return []


def fit_memory_to_budget(memory: ConversationMemory, max_tokens: int) -> PreparedMemory:
    """Budget summary, not-yet-compacted turns, and the recent sliding window."""
    all_turns = _group_complete_turns(memory.messages)
    if max_tokens <= 0:
        return PreparedMemory(
            summary="",
            pending_messages=[],
            messages=[],
            token_count=0,
            dropped_messages=len(memory.messages),
            included_turns=0,
            dropped_turns=len(all_turns),
            summary_tokens=0,
            pending_tokens=0,
            recent_tokens=0,
            included_pending_turns=0,
            dropped_pending_turns=max(
                0,
                len(all_turns) - settings.context_short_term_max_turns,
            ),
        )

    max_turns = settings.context_short_term_max_turns
    recent_candidates = all_turns[-max_turns:] if max_turns > 0 else []
    pending_candidates = (
        all_turns[:-max_turns] if max_turns > 0 else list(all_turns)
    )
    summary = ""
    if memory.summary:
        summary_budget = min(
            settings.context_summary_max_tokens,
            max_tokens if not all_turns else max_tokens // 4,
        )
        summary_budget = max(
            0,
            summary_budget - count_tokens("Earlier conversation summary:\n"),
        )
        summary = truncate_to_tokens(memory.summary, summary_budget)

    recent_max_tokens = min(settings.context_short_term_max_tokens, max_tokens)
    selected_turns: list[ConversationTurn] = []
    selected_messages: list[Message] = []
    for turn in reversed(recent_candidates):
        proposed_turns = [turn] + selected_turns
        proposed_messages = _flatten_turns(proposed_turns)
        if (
            count_tokens(format_memory_for_prompt("", proposed_messages))
            <= recent_max_tokens
            and count_tokens(format_memory_for_prompt(summary, proposed_messages))
            <= max_tokens
        ):
            selected_turns = proposed_turns
            selected_messages = proposed_messages
            continue

        if not selected_turns:
            selected_messages = _truncate_turn_to_budget(
                turn,
                summary,
                max_tokens,
                recent_max_tokens,
            )
            if selected_messages:
                selected_turns = [turn]
        break

    pending_max_tokens = min(settings.context_pending_memory_max_tokens, max_tokens)
    selected_pending_turns: list[ConversationTurn] = []
    selected_pending_messages: list[Message] = []
    for turn in reversed(pending_candidates):
        proposed_turns = [turn] + selected_pending_turns
        proposed_messages = _flatten_turns(proposed_turns)
        if (
            count_tokens(format_memory_for_prompt("", [], proposed_messages))
            <= pending_max_tokens
            and count_tokens(
                format_memory_for_prompt(summary, selected_messages, proposed_messages)
            )
            <= max_tokens
        ):
            selected_pending_turns = proposed_turns
            selected_pending_messages = proposed_messages
            continue

        if not selected_pending_turns:
            selected_pending_messages = _truncate_pending_turn_to_budget(
                turn,
                summary,
                selected_messages,
                max_tokens,
                pending_max_tokens,
            )
            if selected_pending_messages:
                selected_pending_turns = [turn]
        break

    rendered = format_memory_for_prompt(
        summary,
        selected_messages,
        selected_pending_messages,
    )
    recent_tokens = count_tokens(format_memory_for_prompt("", selected_messages))
    pending_tokens = count_tokens(
        format_memory_for_prompt("", [], selected_pending_messages)
    )
    exposed_messages = len(selected_messages) + len(selected_pending_messages)
    return PreparedMemory(
        summary=summary,
        pending_messages=selected_pending_messages,
        messages=selected_messages,
        token_count=count_tokens(rendered),
        dropped_messages=max(0, len(memory.messages) - exposed_messages),
        included_turns=len(selected_turns),
        dropped_turns=max(
            0,
            len(all_turns) - len(selected_turns) - len(selected_pending_turns),
        ),
        summary_tokens=count_tokens(summary),
        pending_tokens=pending_tokens,
        recent_tokens=recent_tokens,
        included_pending_turns=len(selected_pending_turns),
        dropped_pending_turns=max(
            0,
            len(pending_candidates) - len(selected_pending_turns),
        ),
    )


def prepare_routing_memory(
    question: str,
    memory: ConversationMemory,
    system_prompt: str,
) -> PreparedMemory:
    """Budget memory for the routing/query-rewrite LLM call."""
    input_limit = (
        settings.llm_context_window
        - settings.context_routing_output_tokens
        - settings.context_safety_margin_tokens
    )
    fixed_tokens = count_tokens(system_prompt) + count_tokens(question) + 16
    available = min(
        settings.context_routing_history_max_tokens,
        max(0, input_limit - fixed_tokens),
    )
    if fixed_tokens > input_limit:
        raise ContextWindowExceededError(
            "The question is too large for the configured LLM context window."
        )
    return fit_memory_to_budget(memory, available)


def _budget_documents(
    documents: list[Document],
    max_tokens: int,
) -> tuple[list[Document], int]:
    selected: list[Document] = []
    if max_tokens <= 0:
        return selected, 0

    for document in documents:
        candidate = selected + [document]
        if count_tokens(format_documents_for_context(candidate)) <= max_tokens:
            selected.append(document)
            continue

        current_tokens = count_tokens(format_documents_for_context(selected))
        remaining = max_tokens - current_tokens
        header_only = Document(page_content="", metadata=document.metadata)
        header_tokens = count_tokens(format_documents_for_context([header_only])) + 4
        if remaining > header_tokens + 32:
            truncated = Document(
                page_content=truncate_to_tokens(
                    document.page_content,
                    remaining - header_tokens,
                ),
                metadata=dict(document.metadata),
            )
            selected.append(truncated)
        break

    return selected, count_tokens(format_documents_for_context(selected))


def prepare_generation_context(
    question: str,
    memory: ConversationMemory,
    documents: list[Document],
) -> GenerationContext:
    """Build a context plan that is guaranteed to stay within the configured window."""
    input_limit = (
        settings.llm_context_window
        - settings.llm_reserved_output_tokens
        - settings.context_safety_margin_tokens
    )
    empty_system = RAG_SYSTEM_PROMPT.format(history="", context="")
    fixed_tokens = count_tokens(empty_system) + count_tokens(question) + 16
    if fixed_tokens > input_limit:
        raise ContextWindowExceededError(
            "The question is too large for the configured LLM context window."
        )

    payload_budget = max(0, input_limit - fixed_tokens)
    document_floor = min(
        settings.context_document_min_tokens,
        count_tokens(format_documents_for_context(documents)),
    )
    history_budget = min(
        settings.context_history_max_tokens,
        max(0, payload_budget - document_floor),
    )
    prepared_memory = fit_memory_to_budget(memory, history_budget)

    document_budget = max(0, payload_budget - prepared_memory.token_count)
    prepared_documents, document_tokens = _budget_documents(documents, document_budget)

    # Reuse document slack for more recent history, then rebudget documents once.
    expanded_history_budget = min(
        settings.context_history_max_tokens,
        max(0, payload_budget - document_tokens),
    )
    if expanded_history_budget > history_budget:
        prepared_memory = fit_memory_to_budget(memory, expanded_history_budget)
        document_budget = max(0, payload_budget - prepared_memory.token_count)
        prepared_documents, document_tokens = _budget_documents(documents, document_budget)

    history_text = format_memory_for_prompt(
        prepared_memory.summary,
        prepared_memory.messages,
        prepared_memory.pending_messages,
    )
    context_text = format_documents_for_context(prepared_documents)
    rendered_system = RAG_SYSTEM_PROMPT.format(
        history=history_text,
        context=context_text,
    )
    input_tokens = count_tokens(rendered_system) + count_tokens(question) + 16

    # Token concatenation can differ by a few boundary tokens; shrink documents
    # deterministically if the exact rendered prompt exceeds the input limit.
    if input_tokens > input_limit and prepared_documents:
        overflow = input_tokens - input_limit
        prepared_documents, document_tokens = _budget_documents(
            documents,
            max(0, document_budget - overflow - 8),
        )
        context_text = format_documents_for_context(prepared_documents)
        rendered_system = RAG_SYSTEM_PROMPT.format(
            history=history_text,
            context=context_text,
        )
        input_tokens = count_tokens(rendered_system) + count_tokens(question) + 16

    if input_tokens > input_limit:
        raise ContextWindowExceededError(
            "Unable to fit the request into the configured LLM context window."
        )

    included_count = len(prepared_documents)
    plan = GenerationContext(
        summary=prepared_memory.summary,
        pending_history=prepared_memory.pending_messages,
        history=prepared_memory.messages,
        documents=prepared_documents,
        included_document_count=included_count,
        input_tokens=input_tokens,
        history_tokens=prepared_memory.token_count,
        document_tokens=document_tokens,
        dropped_history_messages=prepared_memory.dropped_messages,
        dropped_documents=max(0, len(documents) - included_count),
        included_history_turns=prepared_memory.included_turns,
        dropped_history_turns=prepared_memory.dropped_turns,
        summary_tokens=prepared_memory.summary_tokens,
        summary_revision=memory.summary_revision,
        pending_history_tokens=prepared_memory.pending_tokens,
        included_pending_turns=prepared_memory.included_pending_turns,
        dropped_pending_turns=prepared_memory.dropped_pending_turns,
    )
    logger.info(
        "[CONTEXT] input=%d/%d history=%d summary=%d pending=%d docs=%d "
        "recent_turns=%d pending_turns=%d dropped_turns=%d "
        "dropped_pending_turns=%d dropped_messages=%d dropped_docs=%d "
        "summary_revision=%d "
        "reserved_output=%d safety_margin=%d",
        plan.input_tokens,
        input_limit,
        plan.history_tokens,
        plan.summary_tokens,
        plan.pending_history_tokens,
        plan.document_tokens,
        plan.included_history_turns,
        plan.included_pending_turns,
        plan.dropped_history_turns,
        plan.dropped_pending_turns,
        plan.dropped_history_messages,
        plan.dropped_documents,
        plan.summary_revision,
        settings.llm_reserved_output_tokens,
        settings.context_safety_margin_tokens,
    )
    return plan


def compact_conversation_memory_once(
    conversation_id: str,
    store: ConversationStore | None = None,
) -> CompactionOutcome:
    """
    Attempt one rolling-summary update and return a worker-friendly typed result.

    Full messages remain in SQLite. Only the summary cursor advances, and only
    after structured model output passes validation and the optimistic cursor
    update succeeds.
    """
    if not settings.context_summary_enabled:
        return CompactionOutcome(status=CompactionStatus.NOT_NEEDED)

    store = store or get_conversation_store()
    with _summary_lock:
        try:
            state = store.get_context_state(conversation_id)
        except Exception:
            logger.exception(
                "Conversation compaction could not read state for %s",
                conversation_id,
            )
            return CompactionOutcome(
                status=CompactionStatus.RETRYABLE_FAILURE,
                error_code="state_read_failed",
            )
        if not state:
            return CompactionOutcome(status=CompactionStatus.CONVERSATION_DELETED)

        raw_messages = state["messages"]
        complete_turns = _group_complete_turns(
            raw_messages,
            stop_at_incomplete=True,
        )
        eligible_turn_count = max(
            0,
            len(complete_turns) - settings.context_short_term_max_turns,
        )
        candidates = complete_turns[:eligible_turn_count]
        eligible_tokens = sum(
            count_tokens(
                "\n".join(_format_message(message) for message in turn.messages)
            )
            + 1
            for turn in candidates
        )
        count_triggered = (
            eligible_turn_count >= settings.context_summary_batch_turns
        )
        token_triggered = eligible_tokens >= settings.context_summary_trigger_tokens
        if not candidates or not (count_triggered or token_triggered):
            return CompactionOutcome(
                status=CompactionStatus.NOT_NEEDED,
                summary_revision=state.get("summary_revision", 0),
                summary_tokens=state.get("summary_token_count", 0),
            )

        existing_summary = state.get("summary", "")
        fixed = count_tokens(existing_summary) + 256
        candidate_budget = settings.context_summary_input_tokens - fixed
        if candidate_budget < 64:
            return CompactionOutcome(
                status=CompactionStatus.RETRYABLE_FAILURE,
                error_code="summary_input_budget_exhausted",
                summary_revision=state.get("summary_revision", 0),
                summary_tokens=state.get("summary_token_count", 0),
            )

        selected_turns: list[ConversationTurn] = []
        selected_renderings: list[str] = []
        used = 0
        for turn in candidates:
            rendered = "\n".join(_format_message(message) for message in turn.messages)
            tokens = count_tokens(rendered) + 1
            if used + tokens > candidate_budget:
                if not selected_turns:
                    truncated = truncate_to_tokens(rendered, candidate_budget - 1)
                    if truncated:
                        selected_turns.append(turn)
                        selected_renderings.append(truncated)
                        logger.warning(
                            "Conversation compaction truncated one oversized turn "
                            "for %s to fit the summary input budget",
                            conversation_id,
                        )
                break
            selected_turns.append(turn)
            selected_renderings.append(rendered)
            used += tokens

        if not selected_turns:
            return CompactionOutcome(
                status=CompactionStatus.RETRYABLE_FAILURE,
                error_code="summary_input_budget_exhausted",
                summary_revision=state.get("summary_revision", 0),
                summary_tokens=state.get("summary_token_count", 0),
            )

        transcript = "\n\n".join(
            f"[Turn {index}]\n{rendered}"
            for index, rendered in enumerate(selected_renderings, start=1)
        )
        prompt = (
            "Update the structured rolling conversation memory. Preserve only supported "
            "user goals, constraints, decisions, named entities, unresolved questions, and "
            "important facts. Remove greetings and repetition. Never invent information. "
            "Return one JSON object only, without markdown fences, using exactly this shape:\n"
            '{"schema_version":1,"summary":"...","goals":["..."],'
            '"constraints":["..."],"decisions":["..."],'
            '"open_questions":["..."],"entities":{"name":"value"}}\n'
            f"Keep the entire JSON within {settings.context_summary_max_tokens} tokens. "
            "Use empty arrays or an empty object when a section has no evidence.\n\n"
            f"Existing stored memory:\n{existing_summary or '(none)'}\n\n"
            f"New conversation segment:\n{transcript}"
        )

        try:
            response = get_llm(
                max_tokens=settings.context_summary_max_tokens
            ).invoke(
                [
                    SystemMessage(
                        content="You maintain concise, faithful long-term memory for a chat."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            payload = parse_structured_summary(str(response.content))
            if payload is None:
                logger.warning(
                    "Conversation compaction returned invalid structured JSON for %s; "
                    "summary cursor was not advanced",
                    conversation_id,
                )
                return CompactionOutcome(
                    status=CompactionStatus.RETRYABLE_FAILURE,
                    error_code="invalid_summary_json",
                    summary_revision=state.get("summary_revision", 0),
                    summary_tokens=state.get("summary_token_count", 0),
                )
            summary = serialize_structured_summary(payload)
            summary_tokens = count_tokens(summary)
            if summary_tokens > settings.context_summary_max_tokens:
                logger.warning(
                    "Conversation compaction exceeded summary budget for %s: %d > %d",
                    conversation_id,
                    summary_tokens,
                    settings.context_summary_max_tokens,
                )
                return CompactionOutcome(
                    status=CompactionStatus.RETRYABLE_FAILURE,
                    error_code="summary_budget_exceeded",
                    summary_revision=state.get("summary_revision", 0),
                    summary_tokens=summary_tokens,
                )
            through_message_id = selected_turns[-1].message_ids[-1]
            if through_message_id is None:
                logger.warning(
                    "Conversation compaction found a turn without persisted message IDs for %s",
                    conversation_id,
                )
                return CompactionOutcome(
                    status=CompactionStatus.RETRYABLE_FAILURE,
                    error_code="missing_message_id",
                    summary_revision=state.get("summary_revision", 0),
                    summary_tokens=state.get("summary_token_count", 0),
                )
            updated = store.update_context_summary(
                conversation_id=conversation_id,
                summary=summary,
                through_message_id=through_message_id,
                summary_schema_version=SUMMARY_SCHEMA_VERSION,
                summary_token_count=summary_tokens,
            )
            if updated:
                logger.info(
                    "[CONTEXT] compacted conversation=%s turns=%d messages=%d "
                    "through_id=%d summary_schema=%d summary_revision=%d "
                    "summary_tokens=%d",
                    conversation_id,
                    len(selected_turns),
                    len(selected_turns) * 2,
                    through_message_id,
                    SUMMARY_SCHEMA_VERSION,
                    state.get("summary_revision", 0) + 1,
                    summary_tokens,
                )
                remaining_turns = candidates[len(selected_turns):]
                remaining_tokens = sum(
                    count_tokens(
                        "\n".join(
                            _format_message(message) for message in turn.messages
                        )
                    )
                    + 1
                    for turn in remaining_turns
                )
                needs_follow_up = (
                    len(remaining_turns) >= settings.context_summary_batch_turns
                    or remaining_tokens >= settings.context_summary_trigger_tokens
                )
                return CompactionOutcome(
                    status=CompactionStatus.COMPACTED,
                    through_message_id=through_message_id,
                    compacted_turns=len(selected_turns),
                    summary_revision=state.get("summary_revision", 0) + 1,
                    summary_tokens=summary_tokens,
                    needs_follow_up=needs_follow_up,
                )
            return CompactionOutcome(
                status=CompactionStatus.STALE,
                through_message_id=through_message_id,
                compacted_turns=len(selected_turns),
                summary_revision=state.get("summary_revision", 0),
                summary_tokens=state.get("summary_token_count", 0),
                needs_follow_up=True,
            )
        except Exception:
            logger.warning(
                "Conversation compaction failed for %s; recent history remains available",
                conversation_id,
                exc_info=True,
            )
            return CompactionOutcome(
                status=CompactionStatus.RETRYABLE_FAILURE,
                error_code="compaction_failed",
                summary_revision=state.get("summary_revision", 0),
                summary_tokens=state.get("summary_token_count", 0),
            )


def compact_conversation_memory(
    conversation_id: str,
    store: ConversationStore | None = None,
) -> bool:
    """Compatibility wrapper for callers that only need success/failure."""
    return (
        compact_conversation_memory_once(conversation_id, store=store).status
        == CompactionStatus.COMPACTED
    )
