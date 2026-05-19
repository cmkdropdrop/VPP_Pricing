"""GAN-based scenario pricing for electricity price curves.

This method trains a small dependency-free adversarial model on the supplied
price scenarios.  The generator learns normalised full-horizon price curves and
the discriminator learns to separate empirical curves from generated curves.
Generated scenarios are then dispatched through the same portfolio and risk
pipeline as the deterministic and Monte-Carlo methods.

The implementation is intentionally compact and reproducible.  It is suitable
for research comparisons and smoke-testing an ML scenario-generation workflow;
production use should replace it with a calibrated deep-learning stack, richer
conditioning features, and out-of-sample validation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import ceil, exp, isclose, isfinite, log, sqrt
from typing import Iterable

from vpp_pricing.diagnostics import (
    market_price_diagnostics,
    portfolio_dispatch_diagnostics,
)
from vpp_pricing.market import MarketData
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.methods.rolling_intrinsic import dispatch_with_rolling_battery_policy
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.risk import (
    cashflow_distribution_diagnostics,
    cashflow_risk_metrics,
    normalized_probabilities,
    weighted_mean,
)


def _safe_sigmoid(value: float) -> float:
    if value >= 40.0:
        return 1.0
    if value <= -40.0:
        return 0.0
    return 1.0 / (1.0 + exp(-value))


def _clip(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _latent_sample(rng: random.Random, latent_dim: int) -> list[float]:
    return [rng.gauss(0.0, 1.0) for _ in range(latent_dim)]


def _weighted_sample_index(probabilities: list[float], rng: random.Random) -> int:
    draw = rng.random()
    cumulative = 0.0
    for idx, probability in enumerate(probabilities):
        cumulative += probability
        if draw <= cumulative:
            return idx
    return len(probabilities) - 1


class _Generator:
    def __init__(
        self,
        latent_dim: int,
        hidden_dim: int,
        output_dim: int,
        rng: random.Random,
    ) -> None:
        input_scale = 1.0 / sqrt(latent_dim)
        hidden_scale = 1.0 / sqrt(hidden_dim)
        self.w1 = [
            [rng.gauss(0.0, input_scale) for _ in range(latent_dim)]
            for _ in range(hidden_dim)
        ]
        self.b1 = [0.0 for _ in range(hidden_dim)]
        self.w2 = [
            [rng.gauss(0.0, hidden_scale) for _ in range(hidden_dim)]
            for _ in range(output_dim)
        ]
        self.b2 = [0.0 for _ in range(output_dim)]

    def forward(self, z: list[float]) -> tuple[list[float], list[float]]:
        hidden = [
            _clip(
                _safe_tanh(_dot(weights, z) + bias),
                1.0,
            )
            for weights, bias in zip(self.w1, self.b1)
        ]
        output = [
            _clip(_dot(weights, hidden) + bias, 6.0)
            for weights, bias in zip(self.w2, self.b2)
        ]
        return hidden, output

    def train_from_output_gradient(
        self,
        z: list[float],
        hidden: list[float],
        grad_output: list[float],
        learning_rate: float,
    ) -> None:
        clipped_grad = [_clip(g, 5.0) for g in grad_output]

        grad_hidden = [
            sum(clipped_grad[i] * self.w2[i][j] for i in range(len(self.w2)))
            * (1.0 - hidden[j] * hidden[j])
            for j in range(len(hidden))
        ]

        for i in range(len(self.w2)):
            for j in range(len(hidden)):
                self.w2[i][j] -= learning_rate * clipped_grad[i] * hidden[j]
            self.b2[i] -= learning_rate * clipped_grad[i]

        for j in range(len(self.w1)):
            grad = _clip(grad_hidden[j], 5.0)
            for k in range(len(z)):
                self.w1[j][k] -= learning_rate * grad * z[k]
            self.b1[j] -= learning_rate * grad


class _Discriminator:
    def __init__(self, input_dim: int, hidden_dim: int, rng: random.Random) -> None:
        input_scale = 1.0 / sqrt(input_dim)
        hidden_scale = 1.0 / sqrt(hidden_dim)
        self.w1 = [
            [rng.gauss(0.0, input_scale) for _ in range(input_dim)]
            for _ in range(hidden_dim)
        ]
        self.b1 = [0.0 for _ in range(hidden_dim)]
        self.w2 = [rng.gauss(0.0, hidden_scale) for _ in range(hidden_dim)]
        self.b2 = 0.0

    def forward(self, x: list[float]) -> tuple[list[float], float, float]:
        hidden = [
            _safe_tanh(_dot(weights, x) + bias)
            for weights, bias in zip(self.w1, self.b1)
        ]
        logit = _dot(self.w2, hidden) + self.b2
        probability = _safe_sigmoid(logit)
        return hidden, logit, probability

    def train(self, x: list[float], label: float, learning_rate: float) -> float:
        hidden, _, probability = self.forward(x)
        grad_logit = probability - label
        grad_hidden = [
            grad_logit * self.w2[j] * (1.0 - hidden[j] * hidden[j])
            for j in range(len(hidden))
        ]

        for j in range(len(self.w2)):
            self.w2[j] -= learning_rate * grad_logit * hidden[j]
        self.b2 -= learning_rate * grad_logit

        for j in range(len(self.w1)):
            grad = _clip(grad_hidden[j], 5.0)
            for k in range(len(x)):
                self.w1[j][k] -= learning_rate * grad * x[k]
            self.b1[j] -= learning_rate * grad

        p = min(max(probability, 1e-12), 1.0 - 1e-12)
        return -(label * log(p) + (1.0 - label) * log(1.0 - p))

    def input_gradient_for_label(
        self, x: list[float], label: float
    ) -> tuple[list[float], float, float]:
        hidden, _, probability = self.forward(x)
        grad_logit = probability - label
        grad_hidden = [
            grad_logit * self.w2[j] * (1.0 - hidden[j] * hidden[j])
            for j in range(len(hidden))
        ]
        grad_input = [
            sum(grad_hidden[j] * self.w1[j][k] for j in range(len(hidden)))
            for k in range(len(x))
        ]
        p = min(max(probability, 1e-12), 1.0 - 1e-12)
        loss = -(label * log(p) + (1.0 - label) * log(1.0 - p))
        return grad_input, probability, loss


def _safe_tanh(value: float) -> float:
    if value >= 20.0:
        return 1.0
    if value <= -20.0:
        return -1.0
    e_pos = exp(value)
    e_neg = exp(-value)
    return (e_pos - e_neg) / (e_pos + e_neg)


@dataclass(frozen=True)
class _NormalisedTrainingData:
    vectors: list[list[float]]
    probabilities: list[float]
    means: list[float]
    stds: list[float]
    lower_bounds: list[float]
    upper_bounds: list[float]
    global_std: float


def _weighted_step_stats(
    markets: list[MarketData],
    probabilities: list[float],
) -> tuple[list[float], list[float], float]:
    horizon = markets[0].intervals
    means: list[float] = []
    stds: list[float] = []
    all_prices: list[float] = []
    all_weights: list[float] = []

    for step in range(horizon):
        values = [market.prices_eur_per_mwh[step] for market in markets]
        mean = weighted_mean(values, probabilities)
        variance = weighted_mean([(value - mean) ** 2 for value in values], probabilities)
        means.append(mean)
        stds.append(sqrt(max(variance, 0.0)))

    for market, probability in zip(markets, probabilities):
        interval_weight = probability / horizon
        all_prices.extend(market.prices_eur_per_mwh)
        all_weights.extend(interval_weight for _ in range(horizon))

    global_mean = weighted_mean(all_prices, all_weights)
    global_var = weighted_mean(
        [(price - global_mean) ** 2 for price in all_prices], all_weights
    )
    global_std = max(sqrt(max(global_var, 0.0)), 1.0)
    return means, [std if std > 1e-9 else global_std for std in stds], global_std


def _normalise_markets(
    markets: list[MarketData],
    probabilities: list[float],
    *,
    price_tail_multiplier: float,
) -> _NormalisedTrainingData:
    means, stds, global_std = _weighted_step_stats(markets, probabilities)
    vectors = [
        [
            (price - means[step]) / stds[step]
            for step, price in enumerate(market.prices_eur_per_mwh)
        ]
        for market in markets
    ]

    lower_bounds: list[float] = []
    upper_bounds: list[float] = []
    for step in range(markets[0].intervals):
        values = [market.prices_eur_per_mwh[step] for market in markets]
        cushion = max(price_tail_multiplier * stds[step], 0.25 * global_std, 1.0)
        lower_bounds.append(min(values) - cushion)
        upper_bounds.append(max(values) + cushion)

    return _NormalisedTrainingData(
        vectors=vectors,
        probabilities=probabilities,
        means=means,
        stds=stds,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        global_std=global_std,
    )


def _validate_markets(markets: list[MarketData]) -> None:
    if not markets:
        raise ValueError("at least one market scenario is required")
    first = markets[0]
    for market in markets[1:]:
        if market.timestamps != first.timestamps:
            raise ValueError("all GAN training scenarios must use identical timestamps")
        if not isclose(market.timestep_hours, first.timestep_hours, rel_tol=0.0):
            raise ValueError("all GAN training scenarios must use identical timesteps")


def _noisy_vector(
    vector: list[float],
    rng: random.Random,
    observation_noise_std: float,
) -> list[float]:
    if observation_noise_std <= 0.0:
        return list(vector)
    return [value + rng.gauss(0.0, observation_noise_std) for value in vector]


def _train_gan(
    data: _NormalisedTrainingData,
    *,
    latent_dim: int,
    generator_hidden_dim: int,
    discriminator_hidden_dim: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    observation_noise_std: float,
    rng: random.Random,
) -> tuple[_Generator, dict[str, float]]:
    generator = _Generator(
        latent_dim=latent_dim,
        hidden_dim=generator_hidden_dim,
        output_dim=len(data.means),
        rng=rng,
    )
    discriminator = _Discriminator(
        input_dim=len(data.means),
        hidden_dim=discriminator_hidden_dim,
        rng=rng,
    )

    last_disc_loss = 0.0
    last_gen_loss = 0.0
    last_real_score = 0.0
    last_fake_score = 0.0

    for _ in range(epochs):
        disc_loss = 0.0
        gen_loss = 0.0
        real_score = 0.0
        fake_score = 0.0

        for _ in range(batch_size):
            real_idx = _weighted_sample_index(data.probabilities, rng)
            real = _noisy_vector(
                data.vectors[real_idx],
                rng,
                observation_noise_std,
            )
            disc_loss += discriminator.train(real, 1.0, learning_rate)
            real_score += discriminator.forward(real)[2]

            z_disc = _latent_sample(rng, latent_dim)
            _, fake_disc = generator.forward(z_disc)
            disc_loss += discriminator.train(fake_disc, 0.0, learning_rate)
            fake_score += discriminator.forward(fake_disc)[2]

            z_gen = _latent_sample(rng, latent_dim)
            hidden, fake_gen = generator.forward(z_gen)
            grad_input, _, loss = discriminator.input_gradient_for_label(
                fake_gen, 1.0
            )
            generator.train_from_output_gradient(
                z_gen,
                hidden,
                grad_input,
                learning_rate,
            )
            gen_loss += loss

        last_disc_loss = disc_loss / (2.0 * batch_size)
        last_gen_loss = gen_loss / batch_size
        last_real_score = real_score / batch_size
        last_fake_score = fake_score / batch_size

    return generator, {
        "gan_final_discriminator_loss": round(last_disc_loss, 6),
        "gan_final_generator_loss": round(last_gen_loss, 6),
        "gan_final_real_score": round(last_real_score, 6),
        "gan_final_fake_score": round(last_fake_score, 6),
    }


def _inverse_transform_and_clip(
    normalised_prices: Iterable[float],
    data: _NormalisedTrainingData,
) -> tuple[float, ...]:
    prices: list[float] = []
    for step, value in enumerate(normalised_prices):
        raw = data.means[step] + value * data.stds[step]
        bounded = min(max(raw, data.lower_bounds[step]), data.upper_bounds[step])
        prices.append(round(bounded, 4))
    return tuple(prices)


def _generate_paths(
    generator: _Generator,
    data: _NormalisedTrainingData,
    template_market: MarketData,
    *,
    num_paths: int,
    latent_dim: int,
    empirical_blend: float,
    rng: random.Random,
) -> list[MarketData]:
    probability = 1.0 / num_paths
    paths: list[MarketData] = []

    for idx in range(num_paths):
        z = _latent_sample(rng, latent_dim)
        _, generated = generator.forward(z)
        if empirical_blend > 0.0:
            anchor_idx = _weighted_sample_index(data.probabilities, rng)
            anchor = data.vectors[anchor_idx]
            generated = [
                (1.0 - empirical_blend) * value + empirical_blend * anchor_value
                for value, anchor_value in zip(generated, anchor)
            ]
        prices = _inverse_transform_and_clip(generated, data)
        paths.append(
            MarketData(
                timestamps=template_market.timestamps,
                prices_eur_per_mwh=prices,
                timestep_hours=template_market.timestep_hours,
                name=f"gan_{idx:04d}",
                probability=probability,
            )
        )

    return paths


def _mean_abs_curve_error(
    generated_paths: list[MarketData],
    data: _NormalisedTrainingData,
) -> float:
    generated_mean = [
        sum(path.prices_eur_per_mwh[step] for path in generated_paths)
        / len(generated_paths)
        for step in range(len(data.means))
    ]
    return sum(
        abs(generated - empirical)
        for generated, empirical in zip(generated_mean, data.means)
    ) / len(data.means)


@dataclass
class GANPricing:
    """Adversarial ML scenario pricing for electricity price curves.

    The model learns a distribution of full-horizon price curves from the input
    scenarios, generates synthetic curves, and values the portfolio on those
    curves.  Scenario probabilities are used during training-data sampling.
    """

    num_paths: int = 200
    latent_dim: int = 8
    generator_hidden_dim: int = 12
    discriminator_hidden_dim: int = 12
    epochs: int = 250
    batch_size: int = 16
    learning_rate: float = 0.01
    observation_noise_std: float = 0.02
    empirical_blend: float = 0.25
    price_tail_multiplier: float = 3.0
    seed: int | None = 42
    dispatch_window_hours: float | None = None

    @property
    def name(self) -> str:
        return "gan"

    def price(
        self,
        portfolio: VirtualPowerPlant,
        markets: list[MarketData],
        *,
        risk_aversion: float = 0.0,
        alpha: float = 0.05,
    ) -> PricingResult:
        self._validate_parameters()
        _validate_markets(markets)

        rng = random.Random(self.seed)
        base_probs = normalized_probabilities(
            [market.probability for market in markets],
            len(markets),
        )
        training_data = _normalise_markets(
            markets,
            base_probs,
            price_tail_multiplier=self.price_tail_multiplier,
        )
        generator, training_diagnostics = _train_gan(
            training_data,
            latent_dim=self.latent_dim,
            generator_hidden_dim=self.generator_hidden_dim,
            discriminator_hidden_dim=self.discriminator_hidden_dim,
            epochs=self.epochs,
            batch_size=self.batch_size,
            learning_rate=self.learning_rate,
            observation_noise_std=self.observation_noise_std,
            rng=rng,
        )
        synthetic_paths = _generate_paths(
            generator,
            training_data,
            markets[0],
            num_paths=self.num_paths,
            latent_dim=self.latent_dim,
            empirical_blend=self.empirical_blend,
            rng=rng,
        )

        if self.dispatch_window_hours is None:
            results = tuple(portfolio.dispatch(path) for path in synthetic_paths)
            dispatch_policy = "intrinsic_per_generated_path"
            window_by_path: list[int] | None = None
        else:
            window_by_path = [
                max(1, ceil(self.dispatch_window_hours / path.timestep_hours))
                for path in synthetic_paths
            ]
            results = tuple(
                dispatch_with_rolling_battery_policy(portfolio, path, window)
                for path, window in zip(synthetic_paths, window_by_path)
            )
            dispatch_policy = "rolling_intrinsic_per_generated_path"

        cashflows = [result.total_cashflow_eur for result in results]
        probs = normalized_probabilities(
            [path.probability for path in synthetic_paths],
            len(synthetic_paths),
        )
        metrics = cashflow_risk_metrics(
            cashflows,
            probs,
            risk_aversion=risk_aversion,
            alpha=alpha,
        )

        return PricingResult(
            method_name=self.name,
            portfolio_name=portfolio.name,
            expected_value_eur=metrics.expected_value_eur,
            cashflow_at_risk_eur=metrics.cashflow_at_risk_eur,
            conditional_value_at_risk_eur=metrics.conditional_value_at_risk_eur,
            risk_adjusted_value_eur=metrics.risk_adjusted_value_eur,
            scenario_results=results,
            parameters={
                "risk_aversion": risk_aversion,
                "alpha": alpha,
                "num_paths": self.num_paths,
                "latent_dim": self.latent_dim,
                "generator_hidden_dim": self.generator_hidden_dim,
                "discriminator_hidden_dim": self.discriminator_hidden_dim,
                "epochs": self.epochs,
                "batch_size": self.batch_size,
                "learning_rate": self.learning_rate,
                "observation_noise_std": self.observation_noise_std,
                "empirical_blend": self.empirical_blend,
                "price_tail_multiplier": self.price_tail_multiplier,
                "seed": self.seed,
                "dispatch_policy": dispatch_policy,
                "dispatch_window_hours": self.dispatch_window_hours,
            },
            diagnostics={
                "num_training_scenarios": len(markets),
                "num_paths_total": len(synthetic_paths),
                "dispatch_policy": dispatch_policy,
                "dispatch_window_intervals": (
                    sorted(set(window_by_path)) if window_by_path is not None else None
                ),
                "base_scenario_probabilities": {
                    market.name: round(probability, 6)
                    for market, probability in zip(markets, base_probs)
                },
                "gan_generated_mean_abs_curve_error_eur_per_mwh": round(
                    _mean_abs_curve_error(synthetic_paths, training_data),
                    6,
                ),
                "gan_training_global_price_std_eur_per_mwh": round(
                    training_data.global_std,
                    6,
                ),
                **training_diagnostics,
                **metrics.diagnostics(),
                **cashflow_distribution_diagnostics(cashflows, probs),
                **market_price_diagnostics(markets, prefix="base_market"),
                **market_price_diagnostics(synthetic_paths, prefix="generated_market"),
                **portfolio_dispatch_diagnostics(results, probs),
            },
        )

    def _validate_parameters(self) -> None:
        if self.num_paths <= 0:
            raise ValueError("num_paths must be positive")
        if self.latent_dim <= 0:
            raise ValueError("latent_dim must be positive")
        if self.generator_hidden_dim <= 0:
            raise ValueError("generator_hidden_dim must be positive")
        if self.discriminator_hidden_dim <= 0:
            raise ValueError("discriminator_hidden_dim must be positive")
        if self.epochs <= 0:
            raise ValueError("epochs must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.learning_rate <= 0.0 or not isfinite(self.learning_rate):
            raise ValueError("learning_rate must be positive and finite")
        if self.observation_noise_std < 0.0:
            raise ValueError("observation_noise_std must not be negative")
        if not 0.0 <= self.empirical_blend <= 1.0:
            raise ValueError("empirical_blend must be in [0, 1]")
        if self.price_tail_multiplier < 0.0:
            raise ValueError("price_tail_multiplier must not be negative")
        if self.dispatch_window_hours is not None and self.dispatch_window_hours <= 0:
            raise ValueError("dispatch_window_hours must be positive when set")
