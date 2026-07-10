"""LLM provider wrapper: Groq (qwen/qwen3.6-27b) is the main executor,
Gemini (gemini-2.5-flash) is the fallback if Groq errors or times out. Both
are normalized into one ProviderResult so the graph never cares who answered.

Model history: gemma2-9b-it (original brief) -> llama-3.3-70b-versatile (both
deprecated on Groq) -> openai/gpt-oss-120b (Groq's recommended replacement -
but it turned out NOT to support parallel tool calls, which silently broke
multi-fact single-message logging: "met Dr X, discussed Y, call" would only
ever produce ONE tool call no matter how the prompt was worded, since the
model can't return more than one per turn) -> qwen/qwen3.6-27b, Groq's other
recommended replacement, which does support parallel tool calls. Note this
one is tagged "Preview" by Groq (could be pulled with short notice) - if it
ever disappears, swap groq_model back to llama-3.3-70b-versatile in .env,
no code changes needed, since it's deprecated-but-functional through 08/16/26.

Qwen3.6-27b-specific params (different shape than GPT-OSS's reasoning_effort
low/medium/high + include_reasoning):
- reasoning_effort: "default" enables "thinking mode" (better for the
  multi-fact-to-multi-tool-call extraction task), "none" is fast
  non-thinking mode (fine for the plain-text composer, which is just
  paraphrasing already-known facts, not reasoning about anything new).
- reasoning_format="hidden": required whenever tool calling or JSON mode is
  active (the default "raw" format 400s in that combination per Groq's
  docs) - we don't need the reasoning trace anyway, only the final content.
- parallel_tool_calls=True: this is what actually lets a compound message
  ("met Dr X, they were with Y and Z, over a call") produce several tool
  calls in one turn even on a model that supports it - it's a separate
  opt-in flag from model capability, and defaults to being left unsent
  (provider-decided) if not passed explicitly.

_strip_reasoning() is a defensive backstop: even with reasoning_format set
to "hidden", a <think>...</think> block was observed leaking directly into
message.content in respond_node's replies (visible to the rep in chat) -
whether that was this SDK version not forwarding extra_body correctly or a
provider-side quirk, the fix that doesn't depend on either is to strip any
<think> block from text before it's ever used, on every text-producing call
path."""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from groq import Groq
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger("llm_provider")

# reasoning_effort/reasoning_format aren't in the installed groq SDK's
# (0.13.0) typed create() signature yet, even though the raw HTTP API
# supports them - passed via extra_body instead of upgrading the package,
# same "don't fight the installed version" approach as Gemini's HttpOptions
# handling below. Two variants: "thinking mode" for the tool-call extraction
# turn (needs to reason about every fact in a compound message), "non-
# thinking mode" for plain text generation (just paraphrasing, needs speed
# more than depth).
_TOOL_CALL_EXTRA_BODY = {"reasoning_effort": "default", "reasoning_format": "hidden"}
_TEXT_EXTRA_BODY = {"reasoning_effort": "none", "reasoning_format": "hidden"}

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Strip any <think>...</think> reasoning block that leaked into visible
    text content - see module docstring. Safe no-op if there's nothing to
    strip."""
    if not text:
        return text
    return _THINK_TAG_RE.sub("", text).strip()


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResult:
    tool_calls: list[ToolCall] = field(default_factory=list)
    reply: str = ""
    provider_used: str = ""


class LLMProviderError(Exception):
    """Raised only when BOTH main and fallback providers fail."""


class LLMProvider:
    """Clients are built lazily on first use, not at import time - a bad key
    or SDK/env quirk should surface as a per-call fallback, not a boot crash."""

    def __init__(self) -> None:
        self._groq_client = None
        self._gemini_client = None

    @property
    def _groq(self):
        if self._groq_client is None and settings.groq_api_key:
            try:
                self._groq_client = Groq(api_key=settings.groq_api_key, timeout=settings.llm_timeout_seconds)
            except Exception as e:  # noqa: BLE001
                logger.error("Could not init Groq client: %s", e)
        return self._groq_client

    @property
    def _gemini(self):
        if self._gemini_client is None and settings.gemini_api_key:
            try:
                self._gemini_client = self._build_gemini_client()
            except Exception as e:  # noqa: BLE001
                logger.error("Could not init Gemini client: %s", e)
        return self._gemini_client

    def _build_gemini_client(self):
        """Timeout config's shape has changed across google-genai SDK
        versions (types.HttpOptions doesn't exist in every version) - try
        the current API, fall back gracefully instead of letting a version
        mismatch take down the whole fallback path."""
        timeout_ms = int(settings.llm_timeout_seconds * 1000)
        try:
            return genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(timeout=timeout_ms))
        except AttributeError:
            pass
        try:
            return genai.Client(api_key=settings.gemini_api_key, http_options={"timeout": timeout_ms})
        except TypeError:
            pass
        logger.warning("This google-genai version has no request-timeout option; using its default.")
        return genai.Client(api_key=settings.gemini_api_key)

    def generate(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> ProviderResult:
        """Groq first; any exception (rate limit, timeout, bad key) falls back to Gemini."""
        turn_start = time.perf_counter()
        try:
            result = self._call_groq(system_prompt, messages, tools)
            print(result)
            logger.info("LLM turn done via groq in %.2fs", time.perf_counter() - turn_start)
            return result
        except Exception as e:  # noqa: BLE001 - any failure here should trigger fallback, not crash
            logger.warning("Groq failed after %.2fs, falling back to Gemini: %s", time.perf_counter() - turn_start, e)
        try:
            result = self._call_gemini(system_prompt, messages, tools)
            logger.info("LLM turn done via gemini fallback in %.2fs (total)", time.perf_counter() - turn_start)
            return result
        except Exception as e:  # noqa: BLE001
            logger.error("Gemini fallback also failed after %.2fs total: %s", time.perf_counter() - turn_start, e)
            raise LLMProviderError("Both Groq and Gemini failed") from e

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Plain text completion, no tool schemas - for narrative generation
        (suggest_followup's suggestions, respond_node's confirmation text),
        not structured tool-call decisions. Same Groq-then-Gemini fallback
        as generate()."""
        turn_start = time.perf_counter()
        try:
            text = self._call_groq_text(system_prompt, user_prompt)
            logger.info("LLM text call done via groq in %.2fs", time.perf_counter() - turn_start)
            return text
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Groq text call failed after %.2fs, falling back to Gemini: %s",
                time.perf_counter() - turn_start,
                e,
            )
        try:
            text = self._call_gemini_text(system_prompt, user_prompt)
            logger.info("LLM text call done via gemini fallback in %.2fs (total)", time.perf_counter() - turn_start)
            return text
        except Exception as e:  # noqa: BLE001
            logger.error("Gemini text fallback also failed after %.2fs total: %s", time.perf_counter() - turn_start, e)
            raise LLMProviderError("Both Groq and Gemini failed") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _call_groq(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> ProviderResult:
        if not self._groq:
            raise LLMProviderError("GROQ_API_KEY not set")
        started = time.perf_counter()
        resp = self._groq.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=True,  # without this, one compound message -> only ever ONE tool call
            temperature=0.6,  # Qwen3.6 thinking-mode guidance: 1.0 general, 0.6 for precise/structured tasks
            extra_body=_TOOL_CALL_EXTRA_BODY,
        )
        logger.info("groq call: %.2fs, model=%s", time.perf_counter() - started, settings.groq_model)
        msg = resp.choices[0].message
        calls = [
            ToolCall(name=tc.function.name, arguments=_safe_json(tc.function.arguments))
            for tc in (msg.tool_calls or [])
        ]
        return ProviderResult(tool_calls=calls, reply=_strip_reasoning(msg.content or ""), provider_used="groq")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _call_gemini(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> ProviderResult:
        if not self._gemini:
            raise LLMProviderError("GEMINI_API_KEY not set")
        started = time.perf_counter()
        declarations = [types.FunctionDeclaration(**_to_gemini_schema(t)) for t in tools]
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        resp = self._gemini.models.generate_content(
            model=settings.gemini_model,
            contents=f"{system_prompt}\n\n{transcript}",
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                temperature=0.3,
            ),
        )
        logger.info("gemini call: %.2fs, model=%s", time.perf_counter() - started, settings.gemini_model)
        calls: list[ToolCall] = []
        reply = ""
        for part in resp.candidates[0].content.parts:
            if getattr(part, "function_call", None):
                calls.append(ToolCall(name=part.function_call.name, arguments=dict(part.function_call.args)))
            elif getattr(part, "text", None):
                reply += part.text
        return ProviderResult(tool_calls=calls, reply=_strip_reasoning(reply), provider_used="gemini")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _call_groq_text(self, system_prompt: str, user_prompt: str) -> str:
        if not self._groq:
            raise LLMProviderError("GROQ_API_KEY not set")
        resp = self._groq.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,  # Qwen3.6 non-thinking-mode guidance
            extra_body=_TEXT_EXTRA_BODY,
        )
        return _strip_reasoning(resp.choices[0].message.content or "")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _call_gemini_text(self, system_prompt: str, user_prompt: str) -> str:
        if not self._gemini:
            raise LLMProviderError("GEMINI_API_KEY not set")
        resp = self._gemini.models.generate_content(
            model=settings.gemini_model,
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(temperature=0.4),
        )
        return _strip_reasoning(resp.text or "")


def _safe_json(raw: str) -> dict:
    """Tool-call arguments must always parse to a dict - never let bad JSON crash the turn."""
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("Malformed tool-call JSON, using empty args: %r", raw)
        return {}


def _convert_schema_types(schema: dict) -> dict:
    """Gemini wants uppercase type enums (OBJECT/STRING/...) and expects an
    explicit (even if empty) `properties` dict on every OBJECT - plain JSON
    Schema uses lowercase and allows properties to be omitted, so we fix
    both up recursively before handing the schema to the SDK.

    Optional fields use a ["string", "null"] union type (needed for Groq's
    strict mode - see tools.py) which Gemini doesn't support; it uses a
    separate `nullable: bool` instead, so a union type collapses to its
    non-null member plus that flag. enum lists drop the None entry the same
    way, since Gemini's enum values must all be strings."""
    if not isinstance(schema, dict):
        return schema
    converted = dict(schema)
    raw_type = converted.get("type")
    if isinstance(raw_type, list):
        non_null = [t for t in raw_type if t != "null"]
        converted["type"] = (non_null[0] if non_null else "string").upper()
        if "null" in raw_type:
            converted["nullable"] = True
    elif isinstance(raw_type, str):
        converted["type"] = raw_type.upper()
    if "enum" in converted and converted["enum"]:
        converted["enum"] = [e for e in converted["enum"] if e is not None]
    if converted.get("type") == "OBJECT":
        converted["properties"] = {
            k: _convert_schema_types(v) for k, v in (converted.get("properties") or {}).items()
        } or {}
    if converted.get("type") == "ARRAY" and "items" in converted:
        converted["items"] = _convert_schema_types(converted["items"])
    return converted


def _to_gemini_schema(openai_tool: dict) -> dict:
    """Convert an OpenAI/Groq-style tool schema into Gemini FunctionDeclaration kwargs."""
    fn = openai_tool["function"]
    return {
        "name": fn["name"],
        "description": fn["description"],
        "parameters": _convert_schema_types(fn["parameters"]),
    }


provider = LLMProvider()
