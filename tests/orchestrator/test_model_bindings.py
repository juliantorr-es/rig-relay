from rig_relay.orchestrator.model_bindings import (
    build_demo_bindings,
    build_demo_profile_bindings,
    BindingRegistry,
    ModelProviderBinding,
)


def test_local_demo_binding_available():
    registry = build_demo_bindings()
    demo = registry.get("binding-local-demo")
    assert demo is not None
    assert demo.status == "available"
    assert demo.requires_network is False
    assert demo.requires_api_key is False


def test_deepseek_unavailable_by_default():
    registry = build_demo_bindings()
    ds = registry.get("binding-deepseek-default")
    assert ds.status == "unavailable"


def test_binding_for_profile():
    links = build_demo_profile_bindings()
    runtime = [l for l in links if l.profile_id == "profile-runtime-agent"][0]
    assert runtime.default_binding_id == "binding-local-demo"
    assert "binding-local-demo" in runtime.allowed_binding_ids


def test_ralph_binding():
    links = build_demo_profile_bindings()
    ralph = [l for l in links if l.profile_id == "profile-ralph-background"][0]
    assert ralph.default_binding_id == "binding-local-demo"


def test_binding_not_role_identity():
    binding = ModelProviderBinding(
        provider_id="test", model_id="test-model", display_name="Test"
    )
    assert binding.display_name != "orchestrator"
    assert binding.display_name != "ralph"
    assert binding.display_name != "subagent"


def test_register_and_list():
    registry = BindingRegistry()
    b = ModelProviderBinding(provider_id="x", model_id="y", status="available")
    registry.register(b)
    assert len(registry.available()) == 1
    assert len(registry.list_all()) == 1
