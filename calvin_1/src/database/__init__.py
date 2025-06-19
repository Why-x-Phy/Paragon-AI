# This file makes database a proper Python package

from .production_db import (
    get_db_manager,
    ProductionDBManager
) 