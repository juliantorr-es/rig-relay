# ACP Setup

Rig Relay can be used in text editors and IDEs that support [Agent Client Protocol](https://agentclientprotocol.com/overview/clients). Rig Relay includes the `rig-relay-acp` tool.
Once you have set up `vibe` with the API keys, you are ready to use `rig-relay-acp` in your editor. Below are the setup instructions for some editors that support ACP.

## Zed

For usage in Zed, we recommend using the [Rig Relay Zed's extension](https://zed.dev/extensions/rig-relay). Alternatively, you can set up a local install as follows:

1. Go to `~/.config/zed/settings.json` and, under the `agent_servers` JSON object, add the following key-value pair to invoke the `rig-relay-acp` command. Here is the snippet:

```json
{
   "agent_servers": {
      "Rig Relay": {
         "type": "custom",
         "command": "rig-relay-acp",
         "args": [],
         "env": {}
      }
   }
}
```

1. In the `New Thread` pane on the right, select the `vibe` agent and start the conversation.

## JetBrains IDEs

For using Rig Relay in JetBrains IDEs, you'll need to have the [Jetbrains AI Assistant extension](https://plugins.jetbrains.com/plugin/22282-jetbrains-ai-assistant) installed

### Version 2025.3 or later

1. Open settings, then go to `Tools > AI Assistant > Agents`. Search for `Rig Relay`, click install

2. Open AI Assistant. You should be able to select Rig Relay from the agent selector (if you're not authenticated yet, you will be prompted to do so).

### Legacy method

1. Add the following snippet to your JetBrains IDE acp.json ([documentation](https://www.jetbrains.com/help/ai-assistant/acp.html)):

```json
{
  "agent_servers": {
    "Rig Relay": {
      "command": "rig-relay-acp",
    }
  }
}
```

1. In the AI Chat agent selector, select the new Rig Relay agent and start the conversation.

## Neovim (using avante.nvim)

Add Rig Relay in the acp_providers section of your configuration

```lua
{
  acp_providers = {
    ["rig-relay"] = {
      command = "rig-relay-acp",
      env = {
         DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY"), -- necessary if you setup Rig Relay manually
      },
    }
  }
}
```
