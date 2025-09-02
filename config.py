from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # mem0 aget config
    mem0_agent_id: str = "nekro-agent"

    # mem0 llm config
    mem0_llm_model: str = "gpt-4o"
    mem0_llm_temperature: float = 0.0

    # mem0 embedding config
    mem0_embedding_model: str = "text-embedding-3-large"

    # mem0 vector store config
    mem0_vector_store_provider: str = "qdrant"
    mem0_vector_store_config: dict = {
        "host": "localhost",
        "port": 6333,
    }


config = Config()
