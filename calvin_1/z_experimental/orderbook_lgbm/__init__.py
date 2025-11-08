"""
Orderbook LightGBM Trading Model

A minimal LightGBM-based crypto trading model focused on orderbook features.
"""

__version__ = "0.1.0"
__author__ = "Calvin AI Team"

from .config import get_config, validate_config, Config
from .data_loader import get_data_loader, DataLoader
from .features import get_feature_engineer, make_features, FeatureEngineer
from .trainer import get_trainer, LGBMTrainer, create_time_based_split
from .eval import get_evaluator, ModelEvaluator, evaluate_saved_model
from .utils import setup_logging, save_json, load_json

__all__ = [
    # Config
    'get_config', 'validate_config', 'Config',

    # Data loading
    'get_data_loader', 'DataLoader',

    # Features
    'get_feature_engineer', 'make_features', 'FeatureEngineer',

    # Training
    'get_trainer', 'LGBMTrainer', 'create_time_based_split',

    # Evaluation
    'get_evaluator', 'ModelEvaluator', 'evaluate_saved_model',

    # Utilities
    'setup_logging', 'save_json', 'load_json'
]
