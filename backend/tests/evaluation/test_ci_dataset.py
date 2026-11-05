from app.evaluation.ci_dataset import CI_SCENARIOS


def test_every_scenario_has_a_relevant_chunk():
    for scenario in CI_SCENARIOS:
        paths = {c.relative_path for c in scenario.chunks}
        assert scenario.relevant_relative_path in paths


def test_scenario_ids_and_queries_are_unique():
    assert len({s.id for s in CI_SCENARIOS}) == len(CI_SCENARIOS)
    assert len({s.query for s in CI_SCENARIOS}) == len(CI_SCENARIOS)


def test_every_chunk_embedding_is_the_expected_dimension():
    for scenario in CI_SCENARIOS:
        for chunk in scenario.chunks:
            assert len(chunk.embedding) == 1536


def test_scenarios_use_disjoint_embedding_dimensions():
    # Each scenario's own chunks share dimensions with each other by design
    # (target/vector_noise/keyword_noise all reference the same base
    # dimension) — but no two *different* scenarios may share a dimension,
    # or seeding them all into one module at once (as run_ci_eval does)
    # would let one scenario's vector signal bleed into another's.
    seen: set[int] = set()
    for scenario in CI_SCENARIOS:
        scenario_dims: set[int] = set()
        for chunk in scenario.chunks:
            scenario_dims |= {i for i, v in enumerate(chunk.embedding) if v != 0.0}
        assert not (scenario_dims & seen), f"dimension overlap in scenario {scenario.id!r}"
        seen |= scenario_dims
