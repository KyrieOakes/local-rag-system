"""
Server-side conversation memory and prompt-budget management.

This module is the single source of truth for context handling:
- restores persisted memory from SQLite by conversation_id;
- reconciles it with client-side messages that may not be persisted yet;
- keeps a rolling summary plus recent verbatim messages;
- uses a tokenizer-based budget for routing and answer-generation prompts;
- budgets system instructions, question, history, documents, safety margin,
  and reserved output tokens as one context window.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
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


class ContextWindowExceededError(ValueError):
    """Raised when the current question alone cannot fit the configured window."""


@dataclass(frozen=True)
class ConversationMemory:
    """Long-term summary plus recent verbatim conversation messages."""

    summary: str
    messages: list[Message]
    source: str


@dataclass(frozen=True)
class PreparedMemory:
    """A token-budgeted view of conversation memory."""

    summary: str
    messages: list[Message]
    token_count: int
    dropped_messages: int


@dataclass(frozen=True)
class GenerationContext:
    """Fully budgeted inputs for the final RAG generation call."""

    summary: str
    history: list[Message]
    documents: list[Document]
    included_document_count: int
    input_tokens: int
    history_tokens: int
    document_tokens: int
    dropped_history_messages: int
    dropped_documents: int


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


def _as_message(raw) -> Message:
    if isinstance(raw, Message):
        return raw
    if isinstance(raw, dict):
        return Message(role=raw["role"], content=raw["content"])
    return Message(role=raw.role, content=raw.content)


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
    logger.info(
        "[CONTEXT] restored conversation=%s summary_tokens=%d persisted_messages=%d "
        "client_messages=%d merged_messages=%d",
        conversation_id,
        count_tokens(state.get("summary", "")),
        len(persisted),
        len(client_messages),
        len(merged),
    )
    return ConversationMemory(
        summary=state.get("summary", ""),
        messages=merged,
        source="server",
    )


def _format_message(message: Message) -> str:
    role_label = "User" if message.role == "user" else "Assistant"
    return f"{role_label}: {message.content}"


def format_memory_for_prompt(summary: str, messages: list[Message]) -> str:
    """Render summary and recent messages into a stable prompt section."""
    sections = []
    if summary:
        sections.append(f"Earlier conversation summary:\n{summary}")
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


def fit_memory_to_budget(memory: ConversationMemory, max_tokens: int) -> PreparedMemory:
    """Keep the rolling summary and newest complete messages within a token budget."""
    if max_tokens <= 0:
        return PreparedMemory("", [], 0, len(memory.messages))

    summary = ""
    if memory.summary:
        summary_budget = min(
            settings.context_summary_max_tokens,
            max_tokens if not memory.messages else max_tokens // 4,
        )
        summary_budget = max(
            0,
            summary_budget - count_tokens("Earlier conversation summary:\n"),
        )
        summary = truncate_to_tokens(memory.summary, summary_budget)

    selected: list[Message] = []
    for message in reversed(memory.messages):
        candidate = [message] + selected
        if count_tokens(format_memory_for_prompt(summary, candidate)) <= max_tokens:
            selected = candidate
            continue

        # Preserve some content when even the newest single message is oversized.
        if not selected:
            role_prefix = "User: " if message.role == "user" else "Assistant: "
            empty_message = Message(role=message.role, content="")
            fixed_tokens = count_tokens(
                format_memory_for_prompt(summary, [empty_message])
            )
            content_budget = max(
                0,
                max_tokens - fixed_tokens - count_tokens(role_prefix),
            )
            truncated_message = Message(
                role=message.role,
                content=truncate_to_tokens(message.content, content_budget),
            )
            if (
                count_tokens(format_memory_for_prompt(summary, [truncated_message]))
                <= max_tokens
            ):
                selected = [truncated_message]
        break

    rendered = format_memory_for_prompt(summary, selected)
    return PreparedMemory(
        summary=summary,
        messages=selected,
        token_count=count_tokens(rendered),
        dropped_messages=max(0, len(memory.messages) - len(selected)),
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
        history=prepared_memory.messages,
        documents=prepared_documents,
        included_document_count=included_count,
        input_tokens=input_tokens,
        history_tokens=prepared_memory.token_count,
        document_tokens=document_tokens,
        dropped_history_messages=prepared_memory.dropped_messages,
        dropped_documents=max(0, len(documents) - included_count),
    )
    logger.info(
        "[CONTEXT] input=%d/%d history=%d docs=%d dropped_messages=%d dropped_docs=%d "
        "reserved_output=%d safety_margin=%d",
        plan.input_tokens,
        input_limit,
        plan.history_tokens,
        plan.document_tokens,
        plan.dropped_history_messages,
        plan.dropped_documents,
        settings.llm_reserved_output_tokens,
        settings.context_safety_margin_tokens,
    )
    return plan


def compact_conversation_memory(
    conversation_id: str,
    store: ConversationStore | None = None,
) -> bool:
    """
    Summarize older unsummarized messages while retaining recent verbatim turns.

    This is best-effort and intended to run after the response has been persisted.
    Full original messages remain in SQLite for display/audit; only the model-facing
    memory cursor advances.
    """
    if not settings.context_summary_enabled:
        return False

    store = store or get_conversation_store()
    with _summary_lock:
        state = store.get_context_state(conversation_id)
        if not state:
            return False

        raw_messages = state["messages"]
        eligible_count = (
            len(raw_messages)
            - settings.context_summary_keep_recent_messages
        )
        if eligible_count < settings.context_summary_batch_messages:
            return False

        candidates = raw_messages[:eligible_count]
        existing_summary = state.get("summary", "")
        fixed = count_tokens(existing_summary) + 128
        candidate_budget = max(
            128,
            settings.context_summary_input_tokens - fixed,
        )

        selected = []
        used = 0
        for raw in candidates:
            message = _as_message(raw)
            rendered = _format_message(message)
            tokens = count_tokens(rendered) + 1
            if used + tokens > candidate_budget:
                break
            selected.append(raw)
            used += tokens

        if not selected:
            return False

        transcript = "\n".join(_format_message(_as_message(raw)) for raw in selected)
        prompt = (
            "Update the rolling conversation summary. Preserve user goals, named entities, "
            "decisions, constraints, unresolved questions, and important factual details. "
            "Remove greetings and repetition. Do not invent information. Return only the "
            f"updated summary, within {settings.context_summary_max_tokens} tokens.\n\n"
            f"Existing summary:\n{existing_summary or '(none)'}\n\n"
            f"New conversation segment:\n{transcript}"
        )

        try:
            response = get_llm().invoke(
                [
                    SystemMessage(
                        content="You maintain concise, faithful long-term memory for a chat."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            summary = truncate_to_tokens(
                str(response.content),
                settings.context_summary_max_tokens,
            )
            through_message_id = selected[-1]["id"]
            updated = store.update_context_summary(
                conversation_id=conversation_id,
                summary=summary,
                through_message_id=through_message_id,
            )
            if updated:
                logger.info(
                    "[CONTEXT] compacted conversation=%s messages=%d through_id=%d "
                    "summary_tokens=%d",
                    conversation_id,
                    len(selected),
                    through_message_id,
                    count_tokens(summary),
                )
            return updated
        except Exception as exc:
            logger.warning(
                "Conversation compaction failed for %s; recent history remains available: %s",
                conversation_id,
                exc,
            )
            return False
