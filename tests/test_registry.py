import pytest
from conftest import FakeProbe, FakeRule

from makermedic.core.errors import DuplicateRegistrationError, UnknownCategoryError
from makermedic.core.registry import Registry


def test_probe_registration() -> None:
    registry = Registry()
    probe = FakeProbe()

    registry.register_probe(probe)

    assert registry.probes() == (probe,)


def test_rule_registration() -> None:
    registry = Registry()
    rule = FakeRule()

    registry.register_rule(rule)

    assert registry.rules() == (rule,)


@pytest.mark.parametrize("component", [FakeProbe(), FakeRule()])
def test_duplicate_component_ids_are_rejected(component: FakeProbe | FakeRule) -> None:
    registry = Registry()
    register = (
        registry.register_probe
        if isinstance(component, FakeProbe)
        else registry.register_rule
    )
    register(component)

    with pytest.raises(DuplicateRegistrationError):
        register(component)


def test_category_filtering_uses_component_metadata() -> None:
    registry = Registry()
    example = FakeProbe(id="probe.example", categories=("example", "shared"))
    other = FakeProbe(id="probe.other", categories=("other",))
    registry.register_probe(example)
    registry.register_probe(other)
    registry.register_rule(FakeRule(category="shared"))

    assert registry.probes("shared") == (example,)
    assert len(registry.rules("shared")) == 1


def test_unknown_category_is_rejected() -> None:
    registry = Registry()
    registry.register_probe(FakeProbe())

    with pytest.raises(UnknownCategoryError, match="unknown"):
        registry.probes("missing")


def test_empty_registry_accepts_unfiltered_selection() -> None:
    registry = Registry()

    assert registry.probes() == ()
    assert registry.rules() == ()
