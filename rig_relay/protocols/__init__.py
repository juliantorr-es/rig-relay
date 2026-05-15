"""rig_relay.protocols — MCP and ACP adapter layers.

MCP: Rig exposes governed tools/resources/prompts to models and hosts.
ACP: Rig presents itself as a governed coding agent to editors/IDEs.

Neither protocol is baked into Rig's core. Adapters translate external
protocol messages into Rig-native mission envelopes, receipts, and
governed tool invocations. The mission envelope is the common substrate.
"""
