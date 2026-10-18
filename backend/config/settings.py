from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_USER: str
    DB_PASS: str
    DB_NAME: str
    DB_PORT: int = 5432
    DB_HOST: str = "localhost"
    SCHEDULE_ENABLE: bool = True
    GEMINI_API_KEY: str
    ARTICLE_EXTRACTION_MAX_RETRY:int = 3
    DEBUG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def DATABASE_URL(self):
        # Select Psycopg 3 explicitly; plain postgresql:// defaults to psycopg2.
        return f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
