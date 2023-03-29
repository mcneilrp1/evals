"""
This file defines the classes for how to manage prompts for different types of
models, i.e., "chat models" vs. "non chat models".
"""
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Text, Union

logger = logging.getLogger(__name__)
ENCODER_LOCK = threading.Lock()

# This is an approximation to the type accepted as the `prompt` field to `openai.Completion.create` calls
OpenAICreatePrompt = Union[str, list[str], list[int], list[list[int]]]

# This is the type accepted as the `prompt` field to `openai.ChatCompletion.create` calls
OpenAIChatMessage = Dict[str, str]  # A message is a dictionary with "role" and "content" keys
OpenAICreateChatPrompt = List[OpenAIChatMessage]  # A chat log is a list of messages


def chat_prompt_to_text_prompt(prompt: OpenAICreateChatPrompt) -> str:
    """
    Render a chat prompt as a text prompt. User and assistant messages are separated by newlines
    and prefixed with "User: " and "Assistant: ", respectively, unless there is only one message.
    System messages have no prefix.
    """
    assert is_chat_prompt(prompt), f"Expected a chat prompt, got {prompt}"
    chat_to_prefixes = {
        # roles
        "system": "",
        "user": "User",
        "assistant": "Assistant",
        # names
        "example_user": "User",
        "example_assistant": "Assistant",
        "tool": "Tool",
    }

    # For a single message, be it system, user, or assistant, just return the message
    if len(prompt) == 1:
        return prompt[0]["content"]

    lines = []
    for msg in prompt:
        role: Optional[Text] = msg.get("role")
        name: Optional[Text] = msg.get("name")
        receiver: Optional[Text] = msg.get("recipient", None)

        prefix = chat_to_prefixes.get(role, role.capitalize())

        # Tool special case
        if name is not None:
            prefix += f" ({name})"

        # Receiver name
        if receiver is not None:
            mapped_receiver = chat_to_prefixes.get(receiver, receiver)
            prefix += f" -> {mapped_receiver}"

        # Add a separator
        if prefix:
            prefix += ": "

        content = msg["content"]
        lines.append(f"{prefix}{content}")

    text = "\n".join(lines)
    text += f"{chat_to_prefixes['assistant']}: "
    return text.lstrip()


def _prepare_chat_prompt(prompt: OpenAICreateChatPrompt) -> OpenAICreateChatPrompt:
    prompts = []
    for msg in prompt:
        role: Text = msg["role"]
        content: Text = msg["content"]
        # TODO: Handle recipient, name, etc.
        if role == "tool":
            name: Optional[Text] = msg.get("name")

            content_prefix = ""

            if name is not None:
                content_prefix += f"Tool ({name}): "

            updated_message = {"role": "assistant", "content": f"{content_prefix}{content}"}
            prompts.append(updated_message)
        elif role == "assistant":
            recipient: Optional[Text] = msg.get("recipient")
            if recipient is not None:
                updated_message = {
                    "role": "assistant",
                    "content": f"To {recipient}: {content}",
                }
                prompts.append(updated_message)
            else:
                prompts.append(msg)

        else:
            prompts.append(msg)

    return prompts


def text_prompt_to_chat_prompt(prompt: str) -> OpenAICreateChatPrompt:
    assert isinstance(prompt, str), f"Expected a text prompt, got {prompt}"
    return [
        {"role": "system", "content": prompt},
    ]


@dataclass
class Prompt(ABC):
    """
    A `Prompt` encapsulates everything required to present the `raw_prompt` in different formats,
    e.g., a normal unadorned format vs. a chat format.
    """

    @abstractmethod
    def to_openai_create_prompt(self):
        """
        Return the actual data to be passed as the `prompt` field to either `openai.ChatCompletion.create`,
        if the model is a chat model, or `openai.Completion.create` otherwise.
        See the above types to see what each API call is able to handle.
        """


def is_chat_prompt(prompt: Prompt) -> bool:
    return isinstance(prompt, list) and all(isinstance(msg, dict) for msg in prompt)


@dataclass
class CompletionPrompt(Prompt):
    """
    A `Prompt` object that wraps prompts to be compatible with non chat models, which use `openai.Completion.create`.
    """

    raw_prompt: Union[OpenAICreatePrompt, OpenAICreateChatPrompt]

    def _render_chat_prompt_as_text(self, prompt: OpenAICreateChatPrompt) -> OpenAICreatePrompt:
        return chat_prompt_to_text_prompt(prompt)

    def to_openai_create_prompt(self) -> OpenAICreatePrompt:
        if is_chat_prompt(self.raw_prompt):
            return self._render_chat_prompt_as_text(self.raw_prompt)
        return self.raw_prompt


@dataclass
class ChatCompletionPrompt(Prompt):
    """
    A `Prompt` object that wraps prompts to be compatible with chat models, which use `openai.ChatCompletion.create`.

    The format expected by chat models is a list of messages, where each message is a dict with "role" and "content" keys.
    """

    raw_prompt: Union[OpenAICreatePrompt, OpenAICreateChatPrompt]

    def _render_text_as_chat_prompt(self, prompt: str) -> OpenAICreateChatPrompt:
        """
        Render a text string as a chat prompt. The default option we adopt here is to simply take the full prompt
        and treat it as a system message.
        """
        return text_prompt_to_chat_prompt(prompt)

    def to_openai_create_prompt(self) -> OpenAICreateChatPrompt:
        if is_chat_prompt(self.raw_prompt):
            return _prepare_chat_prompt(self.raw_prompt)
        return self._render_text_as_chat_prompt(self.raw_prompt)
