from dataclasses import dataclass, field
from pathlib import Path
import math
import yaml
import pandas as pd


@dataclass(frozen=True)
class DataConfig:
    order_book_id: str = "000985.XSHG"
    start_date: str = "2010-01-01"
    end_date: str = "2026-10-30"
    industry_ids: list[str] = field(default_factory=list)
    industry_classification: str = "unspecified"
    small_cap_id: str = "000905.XSHG"
    large_cap_id: str = "000300.XSHG"

    def __post_init__(self):
        if not self.order_book_id or any(c in self.order_book_id for c in "/\\"):
            raise ValueError("order_book_id must be a single instrument identifier")
        if pd.Timestamp(self.start_date) > pd.Timestamp(self.end_date):
            raise ValueError("start_date must precede end_date")


@dataclass(frozen=True)
class ModelConfig:
    n_states: int = 4
    min_train_size: int = 504
    train_window: int = 756
    refit_every: int = 21
    covariance_type: str = "diag"
    n_init: int = 5
    max_iter: int = 500
    reg_covar: float = 0.001
    random_state: int = 42
    clip_quantile: float = 0.01
    model_type: str = "gmm"
    scaler: str = "mad"
    min_component_weight: float = 0.01

    def __post_init__(self):
        if self.n_states < 2 or self.min_train_size < max(30, 5 * self.n_states):
            raise ValueError("Use >=2 states and a sufficiently large training sample")
        if self.train_window < self.min_train_size or self.refit_every < 1:
            raise ValueError("train_window >= min_train_size; refit_every >= 1 required")
        if self.covariance_type not in {"diag", "full", "tied", "spherical"}:
            raise ValueError("Invalid covariance_type")
        if not 0 <= self.clip_quantile < 0.5:
            raise ValueError("clip_quantile must be in [0, 0.5)")
        if self.n_init < 1 or self.max_iter < 1 or not math.isfinite(self.reg_covar) or self.reg_covar <= 0:
            raise ValueError("Invalid GMM numerical settings")
        if self.model_type not in {"gmm", "hmm"} or self.scaler not in {"mad", "standard"}:
            raise ValueError("Invalid model_type or scaler")
        if not 0 <= self.min_component_weight < 1 / self.n_states:
            raise ValueError("min_component_weight must be in [0, 1/n_states)")


@dataclass(frozen=True)
class EvaluationConfig:
    horizons: list[int] = field(default_factory=lambda: [5, 20, 60])
    transaction_cost_bps: float = 10.0
    periods_per_year: int = 252

    def __post_init__(self):
        if not self.horizons or any(not isinstance(h, int) or h < 1 for h in self.horizons):
            raise ValueError("horizons must be positive integers")
        if not math.isfinite(self.transaction_cost_bps) or self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps must be finite and nonnegative")
        if self.periods_per_year < 1:
            raise ValueError("periods_per_year must be positive")


@dataclass(frozen=True)
class ResearchConfig:
    data: DataConfig = field(default_factory=DataConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)

    @classmethod
    def load(cls, path: str | Path):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        unknown = set(raw) - {"data", "model", "evaluation"}
        if unknown:
            raise ValueError(f"Unknown configuration sections: {sorted(unknown)}")
        return cls(DataConfig(**raw.get("data", {})), ModelConfig(**raw.get("model", {})),
                   EvaluationConfig(**raw.get("evaluation", {})))
