# testing.py
# The settings pytest uses. The DB_* variables come from the environment,
# as in CI, or from .env when run locally. manage.py loads .env for
# itself, but pytest doesn't run manage.py.

import dotenv

dotenv.load_dotenv()

from .base import *
