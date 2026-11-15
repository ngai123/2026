"""Central configuration for FinancialNgai app.

Re-exports everything so that ``import config; config.X`` keeps working.
"""
from dotenv import load_dotenv

load_dotenv()

from config.paths import *          # noqa: F401,F403
from config.providers import *      # noqa: F401,F403
from config.scraper_urls import *   # noqa: F401,F403
from config.simulation import *     # noqa: F401,F403
from config.seed_data import *      # noqa: F401,F403
