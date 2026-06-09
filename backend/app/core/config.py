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

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


SETTINGS = Settings()
