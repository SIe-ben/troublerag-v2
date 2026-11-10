import re
from typing import Dict, Tuple, List

class LogSanitizer:
    """
    Scrubs sensitive PII, IPv4 addresses, emails, and credentials from raw 
    error logs before embedding or sending to external LLM APIs.
    """

    def __init__(self):
        # We pre-compile regex patterns inside a dictionary for fast execution.
        # Key = Label of the secret | Value = (Compiled Regex Pattern, Replacement Tag)
        self.rules: Dict[str, Tuple[re.Pattern, str]] = {
            "Database_URI_Password": (
                re.compile(r"(postgres(?:ql)?|mysql|mongodb|redis)://([^:]+):([^@]+)@", re.IGNORECASE),
                r"\1://\2:[REDACTED_DB_PASS]@"
            ),
            "API_Key_or_Token": (
                re.compile(r"\b(Bearer\s+[A-Za-z0-9\-._~+/]+=*|sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,})\b"),
                "[REDACTED_TOKEN]"
            ),
            "IPv4_Address": (
                re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
                "[REDACTED_IP]"
            ),
            "Email_Address": (
                re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
                "[REDACTED_EMAIL]"
            )
        }

    def sanitize(self, raw_log: str) -> Tuple[str, Dict[str, int]]:
        """
        Takes a raw error log string and returns:
        1. cleaned_log: The safe string with secrets replaced.
        2. redaction_stats: A dictionary showing how many secrets of each type were caught.
        """
        cleaned_log = raw_log
        redaction_stats: Dict[str, int] = {}

        for rule_name, (pattern, replacement) in self.rules.items():
            # re.subn() does two things at once: 
            # It replaces all matches AND returns the exact count of replacements made!
            cleaned_log, count = pattern.subn(replacement, cleaned_log)
            
            if count > 0:
                redaction_stats[rule_name] = count

        return cleaned_log, redaction_stats



# SELF-TEST BLOCK: Runs ONLY when you execute 'python core/sanitizer.py' directly

if __name__ == "__main__":
    sanitizer = LogSanitizer()

    sample_dirty_log = (
        "FATAL: Connection failed to postgres://db_admin:SuperSecret99@10.240.12.88:5432/prod_db "
        "for user dev_ops@company.com using token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    )

    print("\n--- 1. ORIGINAL RAW LOG ---")
    print(sample_dirty_log)

    clean_text, stats = sanitizer.sanitize(sample_dirty_log)

    print("\n--- 2. SANITIZED SAFE LOG ---")
    print(clean_text)

    print("\n--- 3. TELEMETRY REPORT ---")
    print(f"Secrets Blocked: {stats}\n")