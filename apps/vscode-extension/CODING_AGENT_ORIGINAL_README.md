# Agent Studio Coding Agent

Agent Studio Coding Agent is a VS Code coding-agent extension backed by a private OpenAI-compatible LLM endpoint.

## Status

Version: 0.0.1  
Stage: Internal Alpha

## Current Capabilities

The agent can:

- Discover repository files
- Search source code
- Read workspace files
- Reason across multiple tool calls
- Propose source-code modifications
- Display proposed changes using VS Code diff
- Require explicit human approval before applying changes
- Apply approved changes using VS Code WorkspaceEdit
- Run controlled verification
- Inspect Git diffs before reporting completion

## Agent Tools

### list_files

Discovers files inside the active VS Code workspace.

### search_code

Searches repository files for symbols, routes, functions, strings, configuration values, and other text.

### read_file

Reads UTF-8 files within the active workspace.

### propose_file_edit

Proposes replacement content for an existing file.

The modification is not applied automatically. VS Code displays the proposed change and requires explicit human approval.

### run_test

Runs controlled verification operations.

Currently supported:

- Python compile verification
- pytest
- npm test

The model is not given unrestricted shell access.

### git_diff

Reads the current Git diff so the agent can verify the actual repository changes before reporting completion.

## Agent Workflow

User Request
-> Repository Discovery
-> Code Search
-> File Inspection
-> Reasoning
-> Proposed Change
-> Human Approval
-> VS Code WorkspaceEdit
-> Verification
-> Git Diff Inspection
-> Final Report

## Model Backend

The extension communicates with an OpenAI-compatible chat-completions endpoint supporting native function calling.

The current development backend uses Gemma 4 31B through llama.cpp on private infrastructure.

## Security Model

- File access is restricted to the active VS Code workspace.
- Workspace path traversal is rejected.
- Source-code modifications require human approval.
- The model cannot approve its own modifications.
- Arbitrary shell execution is not exposed.
- Verification commands are allow-listed.
- Git diff inspection is read-only.

## Development Status

The v0.1 backend supports the initial complete coding-agent loop:

inspect -> reason -> propose -> approve -> modify -> verify -> inspect diff -> report

Planned capabilities include:

- Native Agent Studio sidebar
- Persistent conversations
- Agent state visualization
- Configurable inference endpoints
- Multi-file change transactions
- Policy controls
- MCP integration
- Agent authorization and identity
- Additional development tools
