"""Ансамбль оценки веса: усреднение N параллельных Call 2 покомпонентно."""
from config.bot import config as bot_config
from src.core.llm.two_call_models import (
    WeightComponent,
    WeightEstimationErrorCode,
    WeightItemError,
    WeightItemOk,
)
from src.features.meals import _llm_calls
from src.features.meals._llm_calls import (
    _average_weight_estimates,
    call_weight_estimation,
)


def _ok(**comps) -> WeightItemOk:
    components = [WeightComponent(name=n, weight_g=w) for n, w in comps.items()]
    total = sum(c.weight_g for c in components)
    return WeightItemOk(
        components=components, total_weight_g=total, reasoning="r", verification=""
    )


class _Client:
    provider = "gemini"


class TestAverageWeightEstimates:
    def test_averages_components_by_name(self):
        r = _average_weight_estimates(
            [_ok(рис=200, курица=100), _ok(рис=300, курица=140)]
        )
        by = {c.name: c.weight_g for c in r.components}
        assert by == {"рис": 250.0, "курица": 120.0}
        assert r.total_weight_g == 370.0

    def test_preserves_component_order(self):
        r = _average_weight_estimates([_ok(a=10, b=20), _ok(a=10, b=20)])
        assert [c.name for c in r.components] == ["a", "b"]


class TestEnsembleCall:
    async def _patch(self, monkeypatch, samples, returns):
        """returns — список результатов, отдаётся по одному на каждый вызов."""
        monkeypatch.setattr(bot_config, "weight_ensemble_samples", samples)
        it = iter(returns)
        calls = {"n": 0}

        async def fake(client, user_id, messages, locale):
            calls["n"] += 1
            return next(it)

        monkeypatch.setattr(_llm_calls, "get_weight_estimation_data", fake)
        return calls

    async def test_ensemble_averages_two_ok(self, monkeypatch):
        calls = await self._patch(
            monkeypatch, 2, [_ok(рис=200), _ok(рис=300)]
        )
        result = await call_weight_estimation(_Client(), 42, [], 42)
        assert calls["n"] == 2
        assert result.total_weight_g == 250.0  # усреднено, не 200 и не 300

    async def test_single_sample_no_ensemble(self, monkeypatch):
        calls = await self._patch(monkeypatch, 1, [_ok(рис=200)])
        result = await call_weight_estimation(_Client(), 42, [], 42)
        assert calls["n"] == 1
        assert result.total_weight_g == 200.0

    async def test_fallback_when_fewer_than_two_ok(self, monkeypatch):
        # Первый — ok, второй — error → <2 чистых оценки → вернуть первый как есть
        err = WeightItemError(error_code=WeightEstimationErrorCode.OTHER, error="x")
        await self._patch(monkeypatch, 2, [_ok(рис=200), err])
        result = await call_weight_estimation(_Client(), 42, [], 42)
        assert isinstance(result, WeightItemOk)
        assert result.total_weight_g == 200.0  # не усреднялось
