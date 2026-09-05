import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    razorpay_key_id: str | None = os.getenv("RAZORPAY_KEY_ID") or None
    razorpay_key_secret: str | None = os.getenv("RAZORPAY_KEY_SECRET") or None
    razorpay_webhook_secret: str | None = os.getenv("RAZORPAY_WEBHOOK_SECRET") or None
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./firewall.db")
    default_mandate_ttl_minutes: int = int(os.getenv("DEFAULT_MANDATE_TTL_MINUTES", "20"))
    agent_rate_limit: int = int(os.getenv("AGENT_RATE_LIMIT", "60"))
    agent_rate_limit_global: int = int(os.getenv("AGENT_RATE_LIMIT_GLOBAL", "600"))
    agent_rate_limit_window_seconds: int = int(os.getenv("AGENT_RATE_LIMIT_WINDOW_SECONDS", "60"))
    agent_rate_limit_max_clients: int = int(os.getenv("AGENT_RATE_LIMIT_MAX_CLIENTS", "4096"))
    payment_stale_after_seconds: int = int(os.getenv("PAYMENT_STALE_AFTER_SECONDS", "1800"))
    payment_cleanup_interval_seconds: int = int(os.getenv("PAYMENT_CLEANUP_INTERVAL_SECONDS", "60"))
    payment_cleanup_batch_size: int = int(os.getenv("PAYMENT_CLEANUP_BATCH_SIZE", "100"))

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


settings = Settings()
