"""Tabular reinforcement-learning baseline for battery dispatch.

This method is intentionally small and explicit.  It trains a tabular
Q-learning policy on the supplied price scenarios and then evaluates the
greedy policy on those same scenarios.  It is a didactic baseline for comparing
state-based learning against intrinsic, rolling intrinsic, MC, and GAN
scenario workflows.  It is not a validated trading agent, does not model
order books or DA/ID bidding, and has no out-of-sample guarantee.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import isclose, isfinite, sqrt
from typing import Any

from vpp_pricing.assets import BatteryStorage
from vpp_pricing.diagnostics import (
    market_price_diagnostics,
    portfolio_dispatch_diagnostics,
)
from vpp_pricing.market import MarketData, validate_market_scenarios
from vpp_pricing.methods.base import PricingResult
from vpp_pricing.portfolio import VirtualPowerPlant
from vpp_pricing.results import AssetDispatch, PortfolioDispatch
from vpp_pricing.risk import (
    cashflow_distribution_diagnostics,
    cashflow_risk_metrics,
    normalized_probabilities,
    weighted_quantile,
)


_ACTIONS = ("charge", "idle", "discharge")
_IDLE_IDX = _ACTIONS.index("idle")
_ACTION_TIE_ORDER = (
    _ACTIONS.index("idle"),
    _ACTIONS.index("discharge"),
    _ACTIONS.index("charge"),
)
_State = tuple[int, int, int, int]


@dataclass(frozen=True)
class _PriceDiscretizer:
    edges: tuple[float, ...]
    momentum_threshold: float

    def price_bin(self, price: float) -> int:
        idx = 0
        while idx < len(self.edges) and price > self.edges[idx]:
            idx += 1
        return idx

    def momentum_bin(self, market: MarketData, step: int) -> int:
        if step <= 0:
            return 1
        delta = (
            market.prices_eur_per_mwh[step]
            - market.prices_eur_per_mwh[step - 1]
        )
        if abs(delta) <= self.momentum_threshold:
            return 1
        return 2 if delta > 0.0 else 0


@dataclass
class _BatteryPolicy:
    q_table: dict[_State, list[float]]
    training_rewards: list[float]
    price_discretizer: _PriceDiscretizer


def _weighted_sample_index(probabilities: list[float], rng: random.Random) -> int:
    draw = rng.random()
    cumulative = 0.0
    for idx, probability in enumerate(probabilities):
        cumulative += probability
        if draw <= cumulative:
            return idx
    return len(probabilities) - 1


def _terminal_soc(battery: BatteryStorage) -> float:
    return (
        battery.initial_soc_mwh
        if battery.terminal_soc_mwh is None
        else battery.terminal_soc_mwh
    )


def _can_reach_soc(
    battery: BatteryStorage,
    *,
    current_soc: float,
    target_soc: float,
    intervals_remaining: int,
    timestep_hours: float,
) -> bool:
    if intervals_remaining < 0:
        return False
    charge_efficiency = sqrt(battery.round_trip_efficiency)
    discharge_efficiency = sqrt(battery.round_trip_efficiency)
    max_charge_delta = (
        intervals_remaining * battery.power_mw * timestep_hours * charge_efficiency
    )
    max_discharge_delta = (
        intervals_remaining * battery.power_mw * timestep_hours / discharge_efficiency
    )
    return (
        target_soc <= current_soc + max_charge_delta + 1e-9
        and target_soc >= current_soc - max_discharge_delta - 1e-9
    )


def _validate_battery(battery: BatteryStorage, horizon: int, timestep_hours: float) -> None:
    if battery.capacity_mwh <= 0:
        raise ValueError("capacity_mwh must be positive")
    if battery.power_mw < 0:
        raise ValueError("power_mw must not be negative")
    if not 0 < battery.round_trip_efficiency <= 1:
        raise ValueError("round_trip_efficiency must be in (0, 1]")
    terminal_soc = _terminal_soc(battery)
    for label, soc in (
        ("initial_soc_mwh", battery.initial_soc_mwh),
        ("terminal_soc_mwh", terminal_soc),
    ):
        if soc < -1e-9 or soc > battery.capacity_mwh + 1e-9:
            raise ValueError(f"{label} must be within [0, capacity_mwh]")
    if not _can_reach_soc(
        battery,
        current_soc=battery.initial_soc_mwh,
        target_soc=terminal_soc,
        intervals_remaining=horizon,
        timestep_hours=timestep_hours,
    ):
        raise ValueError("battery terminal SOC is unreachable over the horizon")


def _build_price_discretizer(
    markets: list[MarketData],
    probabilities: list[float],
    price_bins: int,
) -> _PriceDiscretizer:
    values: list[float] = []
    weights: list[float] = []
    move_values: list[float] = []
    move_weights: list[float] = []

    for market, scenario_probability in zip(markets, probabilities):
        interval_weight = scenario_probability / market.intervals
        values.extend(market.prices_eur_per_mwh)
        weights.extend(interval_weight for _ in range(market.intervals))
        if market.intervals > 1:
            move_weight = scenario_probability / (market.intervals - 1)
            for previous, current in zip(
                market.prices_eur_per_mwh, market.prices_eur_per_mwh[1:]
            ):
                move_values.append(abs(current - previous))
                move_weights.append(move_weight)

    edges = tuple(
        weighted_quantile(values, weights, idx / price_bins)
        for idx in range(1, price_bins)
    )
    if move_values:
        threshold = 0.25 * weighted_quantile(move_values, move_weights, 0.5)
    else:
        threshold = 0.0
    return _PriceDiscretizer(edges=edges, momentum_threshold=max(1e-9, threshold))


def _soc_bin(battery: BatteryStorage, soc_mwh: float, soc_bins: int) -> int:
    clipped = min(max(soc_mwh, 0.0), battery.capacity_mwh)
    ratio = clipped / battery.capacity_mwh
    return min(soc_bins - 1, max(0, round(ratio * (soc_bins - 1))))


def _state(
    battery: BatteryStorage,
    market: MarketData,
    step: int,
    soc_mwh: float,
    *,
    soc_bins: int,
    price_discretizer: _PriceDiscretizer,
) -> _State:
    remaining_intervals = market.intervals - step
    return (
        remaining_intervals,
        _soc_bin(battery, soc_mwh, soc_bins),
        price_discretizer.price_bin(market.prices_eur_per_mwh[step]),
        price_discretizer.momentum_bin(market, step),
    )


def _battery_action_transition(
    battery: BatteryStorage,
    market: MarketData,
    *,
    step: int,
    current_soc: float,
    action_idx: int,
) -> tuple[float, float, float] | None:
    action = _ACTIONS[action_idx]
    dt = market.timestep_hours
    price = market.prices_eur_per_mwh[step]
    charge_efficiency = sqrt(battery.round_trip_efficiency)
    discharge_efficiency = sqrt(battery.round_trip_efficiency)
    max_grid_mwh = battery.power_mw * dt
    terminal_soc = _terminal_soc(battery)
    intervals_after = market.intervals - step - 1

    if action == "idle":
        next_soc = current_soc
    elif action == "charge":
        max_delta_soc = max_grid_mwh * charge_efficiency
        if intervals_after == 0:
            target_delta_soc = terminal_soc - current_soc
            if target_delta_soc <= 1e-10:
                return None
            next_soc = current_soc + min(target_delta_soc, max_delta_soc)
        else:
            next_soc = min(battery.capacity_mwh, current_soc + max_delta_soc)
    else:
        max_delta_soc = max_grid_mwh / discharge_efficiency
        if intervals_after == 0:
            target_delta_soc = current_soc - terminal_soc
            if target_delta_soc <= 1e-10:
                return None
            next_soc = current_soc - min(target_delta_soc, max_delta_soc)
        else:
            next_soc = max(0.0, current_soc - max_delta_soc)

    if action != "idle" and isclose(next_soc, current_soc, abs_tol=1e-10):
        return None
    if (
        intervals_after == 0
        and not isclose(next_soc, terminal_soc, rel_tol=0.0, abs_tol=1e-6)
    ):
        return None
    if not _can_reach_soc(
        battery,
        current_soc=next_soc,
        target_soc=terminal_soc,
        intervals_remaining=intervals_after,
        timestep_hours=dt,
    ):
        return None

    transition = battery._transition(
        current_soc=current_soc,
        next_soc=next_soc,
        price=price,
        timestep_hours=dt,
        charge_efficiency=charge_efficiency,
        discharge_efficiency=discharge_efficiency,
    )
    if transition is None:
        return None
    power_mw, cashflow_eur = transition
    return next_soc, power_mw, cashflow_eur


def _feasible_action_indices(
    battery: BatteryStorage,
    market: MarketData,
    *,
    step: int,
    current_soc: float,
) -> list[int]:
    return [
        idx
        for idx in range(len(_ACTIONS))
        if _battery_action_transition(
            battery,
            market,
            step=step,
            current_soc=current_soc,
            action_idx=idx,
        )
        is not None
    ]


def _greedy_action_index(q_values: list[float], feasible_indices: list[int]) -> int:
    best_value = max(q_values[idx] for idx in feasible_indices)
    tied = [
        idx
        for idx in feasible_indices
        if isclose(q_values[idx], best_value, rel_tol=0.0, abs_tol=1e-12)
    ]
    for preferred in _ACTION_TIE_ORDER:
        if preferred in tied:
            return preferred
    return tied[0]


def _select_action_index(
    q_values: list[float],
    feasible_indices: list[int],
    *,
    epsilon: float,
    rng: random.Random,
) -> int:
    if rng.random() < epsilon:
        return rng.choice(feasible_indices)
    return _greedy_action_index(q_values, feasible_indices)


def _mean_last_training_rewards(policies: list[_BatteryPolicy]) -> float:
    values: list[float] = []
    for policy in policies:
        if not policy.training_rewards:
            continue
        tail_count = max(1, len(policy.training_rewards) // 10)
        values.extend(policy.training_rewards[-tail_count:])
    return sum(values) / len(values) if values else 0.0


def _dispatch_battery_with_policy(
    battery: BatteryStorage,
    market: MarketData,
    policy: _BatteryPolicy,
    *,
    soc_bins: int,
) -> AssetDispatch:
    soc = battery.initial_soc_mwh
    power_out: list[float] = []
    cashflow_out: list[float] = []
    soc_path: list[float] = []
    action_path: list[str] = []

    for step in range(market.intervals):
        state = _state(
            battery,
            market,
            step,
            soc,
            soc_bins=soc_bins,
            price_discretizer=policy.price_discretizer,
        )
        feasible_indices = _feasible_action_indices(
            battery,
            market,
            step=step,
            current_soc=soc,
        )
        if not feasible_indices:
            raise ValueError("RL battery policy has no feasible action")
        q_values = policy.q_table.get(state, [0.0 for _ in _ACTIONS])
        action_idx = _greedy_action_index(q_values, feasible_indices)
        transition = _battery_action_transition(
            battery,
            market,
            step=step,
            current_soc=soc,
            action_idx=action_idx,
        )
        if transition is None:
            raise RuntimeError("greedy RL action became infeasible")
        soc, power_mw, cashflow_eur = transition
        power_out.append(power_mw)
        cashflow_out.append(cashflow_eur)
        soc_path.append(soc)
        action_path.append(_ACTIONS[action_idx])

    throughput_mwh = sum(abs(power_mw) * market.timestep_hours for power_mw in power_out)
    return AssetDispatch(
        asset_name=battery.name,
        asset_type="battery",
        power_mw=tuple(power_out),
        cashflow_eur=tuple(cashflow_out),
        metadata={
            "capacity_mwh": battery.capacity_mwh,
            "power_mw": battery.power_mw,
            "round_trip_efficiency": battery.round_trip_efficiency,
            "initial_soc_mwh": battery.initial_soc_mwh,
            "terminal_soc_mwh": round(soc, 6),
            "policy": "tabular_q_learning_greedy",
            "soc_bins": soc_bins,
            "soc_mwh": [round(value, 6) for value in soc_path],
            "actions": action_path,
            "throughput_mwh": round(throughput_mwh, 6),
            "equivalent_cycles": round(
                throughput_mwh / (2.0 * battery.capacity_mwh), 6
            ),
        },
    )


def _dispatch_portfolio_with_rl_policies(
    portfolio: VirtualPowerPlant,
    market: MarketData,
    policies: list[_BatteryPolicy],
    *,
    soc_bins: int,
) -> PortfolioDispatch:
    dispatches: list[AssetDispatch] = []
    battery_idx = 0
    for asset in portfolio.assets:
        if isinstance(asset, BatteryStorage):
            dispatches.append(
                _dispatch_battery_with_policy(
                    asset,
                    market,
                    policies[battery_idx],
                    soc_bins=soc_bins,
                )
            )
            battery_idx += 1
        else:
            dispatches.append(asset.dispatch(market))

    return PortfolioDispatch(
        portfolio_name=portfolio.name,
        market_name=market.name,
        timestamps=market.timestamps,
        prices_eur_per_mwh=market.prices_eur_per_mwh,
        timestep_hours=market.timestep_hours,
        asset_dispatches=tuple(dispatches),
    )


@dataclass
class ReinforcementLearningPricing:
    """Lightweight tabular Q-learning baseline for battery dispatch."""

    episodes: int = 500
    learning_rate: float = 0.20
    discount_factor: float = 0.95
    epsilon: float = 0.25
    epsilon_decay: float = 0.995
    soc_bins: int = 11
    price_bins: int = 8
    seed: int | None = 42

    @property
    def name(self) -> str:
        return "rl"

    def price(
        self,
        portfolio: VirtualPowerPlant,
        markets: list[MarketData],
        *,
        risk_aversion: float = 0.0,
        alpha: float = 0.05,
    ) -> PricingResult:
        self._validate_parameters()
        validate_market_scenarios(markets)

        probabilities = normalized_probabilities(
            [market.probability for market in markets],
            len(markets),
        )
        price_discretizer = _build_price_discretizer(
            markets,
            probabilities,
            self.price_bins,
        )
        rng = random.Random(self.seed)

        battery_assets = [
            asset for asset in portfolio.assets if isinstance(asset, BatteryStorage)
        ]
        policies: list[_BatteryPolicy] = []
        for battery in battery_assets:
            _validate_battery(
                battery,
                horizon=markets[0].intervals,
                timestep_hours=markets[0].timestep_hours,
            )
            policies.append(
                self._train_battery_policy(
                    battery,
                    markets,
                    probabilities,
                    price_discretizer,
                    rng,
                )
            )

        if battery_assets:
            results = tuple(
                _dispatch_portfolio_with_rl_policies(
                    portfolio,
                    market,
                    policies,
                    soc_bins=self.soc_bins,
                )
                for market in markets
            )
        else:
            results = tuple(portfolio.dispatch(market) for market in markets)

        cashflows = [result.total_cashflow_eur for result in results]
        metrics = cashflow_risk_metrics(
            cashflows,
            probabilities,
            risk_aversion=risk_aversion,
            alpha=alpha,
        )
        warnings = self._warnings(markets, battery_assets)

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
                "episodes": self.episodes,
                "learning_rate": self.learning_rate,
                "discount_factor": self.discount_factor,
                "epsilon": self.epsilon,
                "epsilon_decay": self.epsilon_decay,
                "soc_bins": self.soc_bins,
                "price_bins": self.price_bins,
                "seed": self.seed,
                "action_space": list(_ACTIONS),
            },
            diagnostics={
                "num_scenarios": len(markets),
                "num_training_scenarios": len(markets),
                "scenario_cashflows_eur": [round(cashflow, 2) for cashflow in cashflows],
                "scenario_probabilities": [round(probability, 6) for probability in probabilities],
                "rl_training_episodes": self.episodes,
                "rl_state_count": sum(len(policy.q_table) for policy in policies),
                "rl_action_count": len(_ACTIONS),
                "rl_epsilon_final": round(
                    self.epsilon * (self.epsilon_decay ** self.episodes),
                    8,
                ),
                "rl_training_reward_mean_last_10pct": round(
                    _mean_last_training_rewards(policies),
                    6,
                ),
                "rl_policy_scope": "battery_only_tabular_q_learning",
                "rl_battery_count": len(battery_assets),
                "rl_price_bin_edges_eur_per_mwh": [
                    round(edge, 6) for edge in price_discretizer.edges
                ],
                "rl_momentum_threshold_eur_per_mwh": round(
                    price_discretizer.momentum_threshold,
                    6,
                ),
                "rl_warnings": warnings,
                **metrics.diagnostics(),
                **cashflow_distribution_diagnostics(cashflows, probabilities, alpha=alpha),
                **market_price_diagnostics(markets),
                **portfolio_dispatch_diagnostics(results, probabilities),
            },
        )

    def _train_battery_policy(
        self,
        battery: BatteryStorage,
        markets: list[MarketData],
        probabilities: list[float],
        price_discretizer: _PriceDiscretizer,
        rng: random.Random,
    ) -> _BatteryPolicy:
        q_table: dict[_State, list[float]] = {}
        training_rewards: list[float] = []

        for episode in range(self.episodes):
            market = markets[_weighted_sample_index(probabilities, rng)]
            soc = battery.initial_soc_mwh
            total_reward = 0.0
            episode_epsilon = self.epsilon * (self.epsilon_decay ** episode)

            for step in range(market.intervals):
                state = _state(
                    battery,
                    market,
                    step,
                    soc,
                    soc_bins=self.soc_bins,
                    price_discretizer=price_discretizer,
                )
                feasible_indices = _feasible_action_indices(
                    battery,
                    market,
                    step=step,
                    current_soc=soc,
                )
                if not feasible_indices:
                    raise ValueError("RL battery training has no feasible action")
                q_values = q_table.setdefault(state, [0.0 for _ in _ACTIONS])
                action_idx = _select_action_index(
                    q_values,
                    feasible_indices,
                    epsilon=episode_epsilon,
                    rng=rng,
                )
                transition = _battery_action_transition(
                    battery,
                    market,
                    step=step,
                    current_soc=soc,
                    action_idx=action_idx,
                )
                if transition is None:
                    raise RuntimeError("sampled RL action became infeasible")
                next_soc, _, reward = transition
                total_reward += reward

                if step == market.intervals - 1:
                    next_best = 0.0
                else:
                    next_state = _state(
                        battery,
                        market,
                        step + 1,
                        next_soc,
                        soc_bins=self.soc_bins,
                        price_discretizer=price_discretizer,
                    )
                    next_feasible = _feasible_action_indices(
                        battery,
                        market,
                        step=step + 1,
                        current_soc=next_soc,
                    )
                    if next_feasible:
                        next_q = q_table.setdefault(
                            next_state,
                            [0.0 for _ in _ACTIONS],
                        )
                        next_best = max(next_q[idx] for idx in next_feasible)
                    else:
                        next_best = 0.0

                target = reward + self.discount_factor * next_best
                q_values[action_idx] += self.learning_rate * (
                    target - q_values[action_idx]
                )
                soc = next_soc

            training_rewards.append(total_reward)

        return _BatteryPolicy(
            q_table=q_table,
            training_rewards=training_rewards,
            price_discretizer=price_discretizer,
        )

    def _warnings(
        self,
        markets: list[MarketData],
        battery_assets: list[BatteryStorage],
    ) -> list[str]:
        warnings: list[str] = []
        if len(markets) < 10:
            warnings.append(
                f"rl: trained on only {len(markets)} price scenarios; tabular "
                "policies can overfit the discretised training set"
            )
        if not battery_assets:
            warnings.append(
                "rl: no battery assets found; method falls back to deterministic "
                "asset dispatch"
            )
        return warnings

    def _validate_parameters(self) -> None:
        if self.episodes <= 0:
            raise ValueError("episodes must be positive")
        if self.learning_rate <= 0.0 or not isfinite(self.learning_rate):
            raise ValueError("learning_rate must be positive and finite")
        if not 0.0 <= self.discount_factor <= 1.0:
            raise ValueError("discount_factor must be in [0, 1]")
        if not 0.0 <= self.epsilon <= 1.0:
            raise ValueError("epsilon must be in [0, 1]")
        if self.epsilon_decay <= 0.0 or self.epsilon_decay > 1.0:
            raise ValueError("epsilon_decay must be in (0, 1]")
        if self.soc_bins < 2:
            raise ValueError("soc_bins must be at least 2")
        if self.price_bins < 1:
            raise ValueError("price_bins must be positive")
