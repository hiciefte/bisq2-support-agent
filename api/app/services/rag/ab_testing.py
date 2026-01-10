"""A/B Testing Framework for RAG system experiments."""

import hashlib
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Literal, Optional

import numpy as np
from scipy import stats  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Maximum number of metrics to retain in memory (prevents unbounded growth)
MAX_METRICS_BUFFER_SIZE = 100_000


class ABTestingService:
    """A/B testing service for comparing RAG system variants."""

    def __init__(self):
        """Initialize A/B testing service."""
        self.variant_weights = {"control": 0.5, "treatment": 0.5}
        self.active_experiments: Dict[str, Dict[str, Any]] = {}
        # Bounded in-memory buffer to avoid unbounded growth in long-running processes
        self._metrics: Deque[Dict[str, Any]] = deque(maxlen=MAX_METRICS_BUFFER_SIZE)

    def assign_variant(
        self, user_id: str, experiment_id: str
    ) -> Literal["control", "treatment"]:
        """
        Assign user to control or treatment group.

        Uses deterministic hashing so the same user always gets the same variant.

        Args:
            user_id: Unique user identifier
            experiment_id: Experiment identifier

        Returns:
            'control' or 'treatment'
        """
        # Create deterministic hash using SHA-256 for consistent variant assignment
        # Note: This is for bucketing, not security, but we use SHA-256 anyway
        hash_input = f"{user_id}:{experiment_id}"
        hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)

        # Assign based on hash value (convert to integer for precise comparison)
        threshold = int(self.variant_weights["control"] * 100)
        if hash_value % 100 < threshold:
            return "control"
        else:
            return "treatment"

    def create_experiment(
        self,
        experiment_id: str,
        name: str,
        description: str,
        control_description: str,
        treatment_description: str,
        primary_metric: str,
        secondary_metrics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new A/B testing experiment.

        Args:
            experiment_id: Unique experiment identifier
            name: Human-readable experiment name
            description: Experiment description
            control_description: Description of control behavior
            treatment_description: Description of treatment behavior
            primary_metric: Primary metric to measure
            secondary_metrics: Additional metrics to track

        Returns:
            Experiment configuration
        """
        experiment = {
            "id": experiment_id,
            "name": name,
            "description": description,
            "control_description": control_description,
            "treatment_description": treatment_description,
            "primary_metric": primary_metric,
            "secondary_metrics": secondary_metrics or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }

        self.active_experiments[experiment_id] = experiment
        logger.info(f"Created experiment: {experiment_id}")

        return experiment

    async def record_metric(
        self,
        experiment_id: str,
        variant: str,
        metric_name: str,
        value: float,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a metric for analysis.

        Args:
            experiment_id: Experiment identifier
            variant: 'control' or 'treatment'
            metric_name: Name of the metric
            value: Metric value
            user_id: Optional user identifier
            metadata: Optional additional metadata
        """
        # Validate experiment exists and is active
        exp = self.active_experiments.get(experiment_id)
        if not exp or exp.get("status") != "active":
            logger.warning(
                f"Ignoring metric for inactive/unknown experiment {experiment_id}"
            )
            return

        # Validate variant
        if variant not in ("control", "treatment"):
            logger.warning(
                f"Ignoring metric with invalid variant {variant} "
                f"for experiment {experiment_id}"
            )
            return

        # Validate metric value is finite (reject NaN/Inf)
        if not np.isfinite(value):
            logger.warning(
                f"Ignoring non-finite metric value for "
                f"{experiment_id}/{variant}/{metric_name}: {value}"
            )
            return

        metric_record = {
            "experiment_id": experiment_id,
            "variant": variant,
            "metric_name": metric_name,
            "value": value,
            "user_id": user_id,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._metrics.append(metric_record)

        logger.debug(
            f"Recorded metric: {experiment_id}/{variant}/{metric_name}={value}"
        )

    def _get_metric_values(
        self, experiment_id: str, variant: str, metric_name: str
    ) -> List[float]:
        """Get all metric values for a variant."""
        return [
            m["value"]
            for m in self._metrics
            if m["experiment_id"] == experiment_id
            and m["variant"] == variant
            and m["metric_name"] == metric_name
        ]

    async def calculate_statistical_significance(
        self, experiment_id: str, metric_name: str
    ) -> Dict[str, Any]:
        """
        Calculate if results are statistically significant.

        Uses independent samples t-test.

        Args:
            experiment_id: Experiment identifier
            metric_name: Metric to analyze

        Returns:
            Analysis results with significance determination
        """
        control_values = self._get_metric_values(experiment_id, "control", metric_name)
        treatment_values = self._get_metric_values(
            experiment_id, "treatment", metric_name
        )

        if len(control_values) < 2 or len(treatment_values) < 2:
            return {
                "error": "Insufficient data",
                "control_samples": len(control_values),
                "treatment_samples": len(treatment_values),
                "minimum_required": 2,
            }

        # Calculate means
        control_mean = float(np.mean(control_values))
        treatment_mean = float(np.mean(treatment_values))

        # Calculate standard deviations
        control_std = float(np.std(control_values, ddof=1))
        treatment_std = float(np.std(treatment_values, ddof=1))

        # Welch's t-test for statistical significance (doesn't assume equal variances)
        t_stat, p_value = stats.ttest_ind(
            control_values, treatment_values, equal_var=False, nan_policy="omit"
        )

        # Handle degenerate distributions (constant values produce NaN p-value)
        if np.isnan(p_value):
            return {
                "error": "Degenerate distribution (p-value is NaN)",
                "control_samples": len(control_values),
                "treatment_samples": len(treatment_values),
            }

        # Calculate effect size (Cohen's d)
        pooled_std = np.sqrt(
            (
                (len(control_values) - 1) * control_std**2
                + (len(treatment_values) - 1) * treatment_std**2
            )
            / (len(control_values) + len(treatment_values) - 2)
        )
        cohens_d = (treatment_mean - control_mean) / pooled_std if pooled_std > 0 else 0

        # Calculate improvement percentage
        improvement = (
            ((treatment_mean - control_mean) / control_mean) * 100
            if control_mean != 0
            else 0
        )

        # Determine significance (p < 0.05)
        significant = p_value < 0.05

        # Calculate confidence interval for treatment effect
        se_diff = np.sqrt(
            (control_std**2 / len(control_values))
            + (treatment_std**2 / len(treatment_values))
        )
        ci_lower = (treatment_mean - control_mean) - 1.96 * se_diff
        ci_upper = (treatment_mean - control_mean) + 1.96 * se_diff

        return {
            "experiment_id": experiment_id,
            "metric_name": metric_name,
            "control_mean": control_mean,
            "treatment_mean": treatment_mean,
            "control_std": control_std,
            "treatment_std": treatment_std,
            "control_samples": len(control_values),
            "treatment_samples": len(treatment_values),
            "improvement": improvement,
            "t_statistic": float(t_stat),
            "p_value": float(p_value),
            "significant": significant,
            "cohens_d": float(cohens_d),
            "confidence_interval": {
                "lower": float(ci_lower),
                "upper": float(ci_upper),
            },
            "recommendation": self._get_recommendation(
                significant, improvement, len(control_values) + len(treatment_values)
            ),
        }

    def _get_recommendation(
        self, significant: bool, improvement: float, sample_size: int
    ) -> str:
        """Generate recommendation based on results."""
        if sample_size < 100:
            return f"Continue experiment - need more samples (current: {sample_size}, recommended: 100+)"

        if not significant:
            return "No significant difference - consider continuing experiment or accepting null hypothesis"

        if improvement > 10:
            return f"Strong positive result (+{improvement:.1f}%) - consider rolling out treatment"
        elif improvement > 0:
            return f"Weak positive result (+{improvement:.1f}%) - consider practical significance"
        elif improvement > -10:
            return (
                f"Weak negative result ({improvement:.1f}%) - treatment may be harmful"
            )
        else:
            return f"Strong negative result ({improvement:.1f}%) - do NOT roll out treatment"

    async def get_experiment_summary(self, experiment_id: str) -> Dict[str, Any]:
        """
        Get summary of experiment results.

        Args:
            experiment_id: Experiment identifier

        Returns:
            Experiment summary with all metrics
        """
        if experiment_id not in self.active_experiments:
            return {"error": f"Experiment {experiment_id} not found"}

        experiment = self.active_experiments[experiment_id]

        # Get all metrics for this experiment
        experiment_metrics = [
            m for m in self._metrics if m["experiment_id"] == experiment_id
        ]

        # Get unique metric names
        metric_names = set(m["metric_name"] for m in experiment_metrics)

        # Calculate significance for each metric
        results = {}
        for metric_name in metric_names:
            results[metric_name] = await self.calculate_statistical_significance(
                experiment_id, metric_name
            )

        return {
            "experiment": experiment,
            "total_samples": len(experiment_metrics),
            "unique_metrics": list(metric_names),
            "results": results,
        }

    def get_all_experiments(self) -> List[Dict[str, Any]]:
        """Get all active experiments."""
        return list(self.active_experiments.values())

    def end_experiment(self, experiment_id: str, conclusion: str) -> Dict[str, Any]:
        """
        End an experiment with conclusion.

        Args:
            experiment_id: Experiment identifier
            conclusion: Final conclusion

        Returns:
            Updated experiment
        """
        if experiment_id not in self.active_experiments:
            return {"error": f"Experiment {experiment_id} not found"}

        self.active_experiments[experiment_id]["status"] = "completed"
        self.active_experiments[experiment_id]["ended_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        self.active_experiments[experiment_id]["conclusion"] = conclusion

        logger.info(f"Ended experiment {experiment_id}: {conclusion}")

        return self.active_experiments[experiment_id]
