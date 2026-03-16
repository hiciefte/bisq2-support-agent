"""Channel-agnostic parser for `!case` ChatOps commands."""

from __future__ import annotations

import difflib

from app.channels.chatops.models import (
    ChatOpsCommand,
    ChatOpsCommandName,
    ChatOpsParseResult,
)

_ALL_COMMANDS = tuple(command.value for command in ChatOpsCommandName)
_IMPLEMENTED_NOW = {
    ChatOpsCommandName.LIST,
    ChatOpsCommandName.VIEW,
    ChatOpsCommandName.CLAIM,
    ChatOpsCommandName.UNCLAIM,
    ChatOpsCommandName.SEND,
    ChatOpsCommandName.EDIT_SEND,
    ChatOpsCommandName.ESCALATE,
    ChatOpsCommandName.RESOLVE,
    ChatOpsCommandName.HELP,
}


class ChatOpsParser:
    """Parse `!case` commands into a typed command object."""

    prefix = "!case"

    def parse(
        self,
        *,
        text: str,
        actor_id: str,
        source_message_id: str,
        room_id: str,
    ) -> ChatOpsParseResult:
        normalized = str(text or "").strip()
        if not normalized.startswith(self.prefix):
            return ChatOpsParseResult(command=None, handled=False)

        remainder = normalized[len(self.prefix) :].strip()
        if not remainder:
            return ChatOpsParseResult(
                command=None,
                handled=True,
                error_message=self._help_message(
                    "Missing command. Example: `!case help`."
                ),
            )

        parts = remainder.split(maxsplit=1)
        raw_name = parts[0].strip().lower()
        raw_args = parts[1].strip() if len(parts) > 1 else ""

        command_name = self._resolve_command_name(raw_name)
        if command_name is None:
            suggestion = self._closest_command(raw_name)
            suffix = f" Did you mean `!case {suggestion}`?" if suggestion else ""
            return ChatOpsParseResult(
                command=None,
                handled=True,
                error_message=self._help_message(
                    f"Unknown command `{raw_name}`.{suffix}"
                ),
            )

        try:
            command = self._build_command(
                command_name=command_name,
                raw_args=raw_args,
                actor_id=actor_id,
                source_message_id=source_message_id,
                room_id=room_id,
                raw_text=normalized,
            )
        except ValueError as exc:
            return ChatOpsParseResult(
                command=None,
                handled=True,
                error_message=self._help_message(str(exc)),
            )
        return ChatOpsParseResult(command=command, handled=True)

    @staticmethod
    def _resolve_command_name(raw_name: str) -> ChatOpsCommandName | None:
        normalized = str(raw_name or "").strip().lower()
        if not normalized:
            return None
        try:
            return ChatOpsCommandName(normalized)
        except ValueError:
            return None

    @staticmethod
    def _closest_command(raw_name: str) -> str | None:
        matches = difflib.get_close_matches(
            str(raw_name or "").strip().lower(),
            _ALL_COMMANDS,
            n=1,
            cutoff=0.6,
        )
        return matches[0] if matches else None

    def _build_command(
        self,
        *,
        command_name: ChatOpsCommandName,
        raw_args: str,
        actor_id: str,
        source_message_id: str,
        room_id: str,
        raw_text: str,
    ) -> ChatOpsCommand:
        case_id: int | None = None
        message: str | None = None
        options: dict[str, str] = {}

        if command_name == ChatOpsCommandName.HELP:
            self._ensure_no_args(command_name, raw_args)
        elif command_name == ChatOpsCommandName.LIST:
            options = self._parse_list_args(raw_args)
        elif command_name in {
            ChatOpsCommandName.VIEW,
            ChatOpsCommandName.CLAIM,
            ChatOpsCommandName.UNCLAIM,
            ChatOpsCommandName.SEND,
        }:
            case_id = self._parse_case_id(command_name, raw_args)
        elif command_name == ChatOpsCommandName.EDIT_SEND:
            case_id, message = self._parse_edit_send(raw_args)
        elif command_name == ChatOpsCommandName.REWRITE:
            case_id, options = self._parse_case_plus_options(
                command_name,
                raw_args,
                allowed_option_keys={"tone"},
            )
        elif command_name == ChatOpsCommandName.ESCALATE:
            case_id, options = self._parse_case_plus_options(
                command_name,
                raw_args,
                allowed_option_keys={"reason"},
            )
        elif command_name == ChatOpsCommandName.RESOLVE:
            case_id, options = self._parse_case_plus_options(
                command_name,
                raw_args,
                allowed_option_keys={"note"},
            )
        elif command_name == ChatOpsCommandName.SNOOZE:
            case_id, options = self._parse_snooze(raw_args)
        elif command_name == ChatOpsCommandName.FAQ_CREATE:
            case_id, options = self._parse_case_plus_options(
                command_name,
                raw_args,
                allowed_option_keys={"category", "protocol"},
            )
        elif command_name == ChatOpsCommandName.FAQ_LINK:
            case_id, options = self._parse_faq_link(raw_args)
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported command `{command_name.value}`.")

        if command_name not in _IMPLEMENTED_NOW:
            options = dict(options)
            options["implemented"] = "false"

        return ChatOpsCommand(
            name=command_name,
            actor_id=str(actor_id or "").strip(),
            source_message_id=str(source_message_id or "").strip(),
            room_id=str(room_id or "").strip(),
            raw_text=raw_text,
            case_id=case_id,
            options=options,
            message=message,
        )

    @staticmethod
    def _ensure_no_args(command_name: ChatOpsCommandName, raw_args: str) -> None:
        if str(raw_args or "").strip():
            raise ValueError(
                f"`!case {command_name.value}` does not accept extra arguments."
            )

    @staticmethod
    def _parse_case_id(command_name: ChatOpsCommandName, raw_args: str) -> int:
        token = str(raw_args or "").strip()
        if not token:
            raise ValueError(
                f"`!case {command_name.value}` requires a case id. Example: `!case {command_name.value} 241`."
            )
        if " " in token:
            raise ValueError(
                f"`!case {command_name.value}` accepts exactly one case id."
            )
        return ChatOpsParser._coerce_case_id(token)

    @staticmethod
    def _coerce_case_id(value: str) -> int:
        token = str(value or "").strip()
        if not token.isdigit():
            raise ValueError(
                f"Invalid case id `{token}`. Case id must be a positive integer."
            )
        return int(token)

    @staticmethod
    def _split_option_tokens(raw_args: str) -> list[str]:
        return [token for token in str(raw_args or "").split() if token.strip()]

    def _parse_list_args(self, raw_args: str) -> dict[str, str]:
        options: dict[str, str] = {}
        for token in self._split_option_tokens(raw_args):
            if "=" in token:
                key, value = token.split("=", 1)
                key = key.strip().lower()
                value = value.strip()
                if key not in {"channel", "limit"}:
                    raise ValueError(
                        f"Unknown option `{key}` for `!case list`. Allowed: channel=..., limit=..."
                    )
                if not value:
                    raise ValueError(f"`{key}` requires a value.")
                options[key] = value
                continue
            if token.lower() not in {"new", "mine", "stale", "escalated"}:
                raise ValueError(
                    "Invalid list scope. Use one of: new, mine, stale, escalated."
                )
            if "scope" in options:
                raise ValueError("`!case list` accepts only one scope.")
            options["scope"] = token.lower()

        if "limit" in options:
            limit = options["limit"]
            if not limit.isdigit() or int(limit) <= 0:
                raise ValueError("`limit` must be a positive integer.")
        if "channel" in options and options["channel"] not in {"matrix", "bisq2"}:
            raise ValueError("`channel` must be `matrix` or `bisq2`.")
        return options

    def _parse_edit_send(self, raw_args: str) -> tuple[int, str]:
        prefix, separator, suffix = str(raw_args or "").partition("::")
        if not separator:
            raise ValueError(
                "`!case edit-send` requires `:: <message>`. Example: `!case edit-send 241 :: Updated reply`."
            )
        case_id = self._parse_case_id(ChatOpsCommandName.EDIT_SEND, prefix.strip())
        message = suffix.strip()
        if not message:
            raise ValueError(
                "`!case edit-send` requires a non-empty message after `::`."
            )
        return case_id, message

    def _parse_case_plus_options(
        self,
        command_name: ChatOpsCommandName,
        raw_args: str,
        *,
        allowed_option_keys: set[str],
    ) -> tuple[int, dict[str, str]]:
        tokens = self._split_option_tokens(raw_args)
        if not tokens:
            raise ValueError(
                f"`!case {command_name.value}` requires a case id. Example: `!case {command_name.value} 241`."
            )
        case_id = self._coerce_case_id(tokens[0])
        options: dict[str, str] = {}
        for token in tokens[1:]:
            if "=" not in token:
                raise ValueError(
                    f"Unexpected argument `{token}` for `!case {command_name.value}`."
                )
            key, value = token.split("=", 1)
            normalized_key = key.strip().lower()
            if normalized_key not in allowed_option_keys:
                allowed = ", ".join(sorted(allowed_option_keys))
                raise ValueError(
                    f"Unknown option `{normalized_key}` for `!case {command_name.value}`. Allowed: {allowed}."
                )
            cleaned_value = value.strip()
            if not cleaned_value:
                raise ValueError(f"`{normalized_key}` requires a value.")
            options[normalized_key] = cleaned_value
        return case_id, options

    def _parse_snooze(self, raw_args: str) -> tuple[int, dict[str, str]]:
        tokens = self._split_option_tokens(raw_args)
        if len(tokens) != 2:
            raise ValueError(
                "`!case snooze` requires a case id and duration. Example: `!case snooze 241 30m`."
            )
        case_id = self._coerce_case_id(tokens[0])
        duration = tokens[1].strip().lower()
        if not duration:
            raise ValueError("`!case snooze` requires a duration like `30m`.")
        return case_id, {"duration": duration}

    def _parse_faq_link(self, raw_args: str) -> tuple[int, dict[str, str]]:
        tokens = self._split_option_tokens(raw_args)
        if len(tokens) != 2:
            raise ValueError(
                "`!case faq-link` requires a case id and faq id. Example: `!case faq-link 241 faq_123`."
            )
        case_id = self._coerce_case_id(tokens[0])
        faq_id = tokens[1].strip()
        if not faq_id:
            raise ValueError("`!case faq-link` requires a non-empty faq id.")
        return case_id, {"faq_id": faq_id}

    @staticmethod
    def _help_message(prefix: str) -> str:
        implemented = ", ".join(command.value for command in _IMPLEMENTED_NOW)
        return f"{prefix} Available now: {implemented}."
