"""API keys and model provider settings."""
import os

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', '')

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "meta-llama/llama-3.2-3b-instruct:free"

# Xiaomi MiMo — OpenAI-compatible endpoint
XIAOMI_API_KEY = os.getenv("XIAOMI_API_KEY", "")
XIAOMI_BASE_URL = os.getenv("XIAOMI_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
XIAOMI_MODEL = os.getenv("XIAOMI_MODEL", "mimo-v2.5-pro")  # also: mimo-v2-pro, mimo-v2-omni, mimo-v2-flash

# Anthropic (used by settings page)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
