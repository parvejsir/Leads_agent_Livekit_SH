from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str

    LIVEKIT_URL: str
    LIVEKIT_API_KEY: str
    LIVEKIT_API_SECRET: str

    DEEPGRAM_API_KEY: str
    GEMINI_API_KEY: str

    # LiveKit outbound SIP trunk ID (from `lk sip outbound create`)
    SIP_OUTBOUND_TRUNK_ID: str

    # Optional: human transfer number for hot leads
    TRANSFER_PHONE_NUMBER: str = ""

    # Max number of outbound calls the agent dials at once. The queue manager
    # dispatches at most this many concurrent jobs; freed slots auto-dial the
    # next pending contact. Scalable beyond 2 (watch provider rate limits).
    MAX_CONCURRENT_CALLS: int = 2

    # When 1, the queue manager skips real LiveKit dispatch (no Twilio calls).
    # Used by concurrency/queue tests to drive the pipeline without dialing.
    QUEUE_DRY_RUN: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


SETTINGS = Settings()
