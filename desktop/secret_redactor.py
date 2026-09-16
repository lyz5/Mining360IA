from __future__ import annotations

import re


class SecretRedactor:
    _patterns = (
        (re.compile(r"(?i)(client[_ -]?secret|password|passwd|access[_ -]?token|refresh[_ -]?token|api[_ -]?key)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
        (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+\-/=]+"), "Bearer [REDACTED]"),
        (re.compile(r"(?i)(sessionid|csrftoken)\s*=\s*[^\s;]+"), r"\1=[REDACTED]"),
        (re.compile(r"(?is)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "[PRIVATE KEY REDACTED]"),
    )

    @classmethod
    def redact(cls, value: object) -> str:
        text = str(value or "")
        for pattern, replacement in cls._patterns:
            text = pattern.sub(replacement, text)
        return text

