# opencode Kit

opencode agent as a Grove Kit - file exploration, code generation, task execution via MCP.

## Prerequisites

npm install -g opencode-ai

Verify: opencode --version

## Tools

### opencode_run

Run opencode agent in a directory with a task prompt.

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| prompt | string | yes | - | Task description |
| directory | string | no | cwd | Working directory |
| model | string | no | opencode/deepseek-v4-flash-free | Model name |
| timeout | number | no | 120 | Timeout in seconds |

### opencode_models

List available opencode models.

## Install

Manual: cp -r kit-opencode ~/.heart-portal/kits/opencode/ && cd ~/.heart-portal/kits/opencode/ && npm install --production

## Notes

- opencode must be installed globally (npm install -g opencode-ai)
- MCP stdio transport - no network ports required
- Free model: opencode/deepseek-v4-flash-free (no API key needed)
