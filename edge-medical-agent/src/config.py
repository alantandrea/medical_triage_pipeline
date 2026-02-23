"""
Configuration settings for MedGemma Triage System.
All values are configurable via environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """All configurable values for the system."""
    
    # Tenant
    tenant_id: str = Field(default="practice-001", alias="TENANT_ID")
    
    # AWS API
    aws_api_url: str = Field(
        default="https://<your-api-id>.execute-api.<region>.amazonaws.com/prod",
        alias="AWS_API_URL"
    )
    aws_api_key: Optional[str] = Field(default=None, alias="AWS_API_KEY")
    
    # Scheduler
    poll_interval_seconds: int = Field(default=60, alias="POLL_INTERVAL_SECONDS")
    max_items_per_poll: int = Field(default=50, alias="MAX_ITEMS_PER_POLL")
    queue_backpressure_threshold: int = Field(default=20, alias="QUEUE_BACKPRESSURE_THRESHOLD")
    
    # Worker
    worker_concurrency: int = Field(default=1, alias="WORKER_CONCURRENCY")
    component: str = Field(default="all", alias="COMPONENT")  # api, scheduler, worker, all
    
    # Dead-letter queue
    dlq_max_retries: int = Field(default=3, alias="DLQ_MAX_RETRIES")
    
    # Model endpoints
    medgemma_27b_url: str = Field(default="http://localhost:8357", alias="MEDGEMMA_27B_URL")
    medgemma_4b_url: str = Field(default="http://localhost:8358", alias="MEDGEMMA_4B_URL")
    
    # Infrastructure
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_database: str = Field(default="medgemma_triage", alias="MONGODB_DATABASE")
    # OpenSearch
    opensearch_url: str = Field(default="http://localhost:9200", alias="OPENSEARCH_URL")
    opensearch_verify_certs: bool = Field(default=False, alias="OPENSEARCH_VERIFY_CERTS")
    
    # Notification thresholds
    threshold_routine: int = Field(default=29, alias="THRESHOLD_ROUTINE")
    threshold_followup: int = Field(default=30, alias="THRESHOLD_FOLLOWUP")
    threshold_important: int = Field(default=50, alias="THRESHOLD_IMPORTANT")
    threshold_urgent: int = Field(default=75, alias="THRESHOLD_URGENT")
    
    # Email
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    from_email: str = Field(default="", alias="FROM_EMAIL")
    clinical_notification_email: str = Field(default="", alias="CLINICAL_NOTIFICATION_EMAIL")
    tech_support_email: str = Field(default="support@yourdomain.com", alias="TECH_SUPPORT_EMAIL")
    
    # Vector analysis
    rapid_change_threshold_percent: float = Field(default=20.0, alias="RAPID_CHANGE_THRESHOLD_PERCENT")
    rapid_change_window_days: int = Field(default=30, alias="RAPID_CHANGE_WINDOW_DAYS")
    max_historical_values: int = Field(default=5, alias="MAX_HISTORICAL_VALUES")
    
    # Tapestry (patient body-map visualization)
    tapestry_enabled: bool = Field(default=False, alias="TAPESTRY_ENABLED")
    
    # LOINC Configuration
    loinc_data_dir: str = Field(default="./data/loinc", alias="LOINC_DATA_DIR")
    loinc_synonyms_file: str = Field(default="./data/loinc/synonyms.json", alias="LOINC_SYNONYMS_FILE")
    loinc_enable_fuzzy: bool = Field(default=False, alias="LOINC_ENABLE_FUZZY")
    loinc_fuzzy_threshold: int = Field(default=80, alias="LOINC_FUZZY_THRESHOLD")
    loinc_cache_size: int = Field(default=1000, alias="LOINC_CACHE_SIZE")
    loinc_cache_ttl_seconds: int = Field(default=3600, alias="LOINC_CACHE_TTL_SECONDS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global settings instance
settings = Settings()
