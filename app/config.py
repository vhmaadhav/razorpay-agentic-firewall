import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    razorpay_key_id: str | None = os.getenv("RAZORPAY_KEY_ID") or None
    razorpay_key_secret: str | None = os.getenv("RAZORPAY_KEY_SECRET") or None
    razorpay_webhook_secret: str | None = os.getenv("RAZORPAY_WEBHOOK_SECRET") or None
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./firewall.db")
    default_mandate_ttl_minutes: int = int(os.getenv("DEFAULT_MANDATE_TTL_MINUTES", "20"))

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


settings = Settings()
