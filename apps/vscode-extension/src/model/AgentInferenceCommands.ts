import * as vscode from 'vscode';

import {
	AGENT_ROLES,
	AgentInferenceConfigService,
	type AgentRole
} from './AgentInferenceConfig';

import {
	probeAgentConnection
} from './AgentConnectionProbe';

type Action =
	| 'configure'
	| 'set-key'
	| 'migrate-key'
	| 'clear-key'
	| 'test'
	| 'settings';

function validEndpoint(
	value: string
): boolean {
	try {
		const url = new URL(value);

		return (
			['http:', 'https:'].includes(url.protocol) &&
			Boolean(url.hostname) &&
			!url.username &&
			!url.password &&
			!url.search &&
			!url.hash
		);
	} catch {
		return false;
	}
}

export function registerAgentInferenceCommands(
	secrets: vscode.SecretStorage
): vscode.Disposable {
	const service =
		new AgentInferenceConfigService(
			secrets
		);

	return vscode.commands.registerCommand(
		'agentStudio.manageAgentInference',
		async () => {
			try {
				const profiles =
					await Promise.all(
						AGENT_ROLES.map(
							role =>
								service.getPublicProfile(
									role
								)
						)
					);

				const selected =
					await vscode.window.showQuickPick(
						profiles.map(
							profile => ({
								label:
									profile.label,
								description:
									profile.enabled
										? 'Enabled'
										: 'Disabled',
								detail:
									`${profile.model} · Node ${profile.node} · Key: ${
										profile.hasApiKey
											? 'stored'
											: 'not configured'
									}`,
								role:
									profile.role
							})
						),
						{
							title:
								'Agent Studio: Select Inference Agent',
							placeHolder:
								'Select the agent to configure or test'
						}
					);

				if (!selected) {
					return;
				}

				const role:
					AgentRole =
					selected.role;

				const actions: Array<{
					label: string;
					id: Action;
				}> = [
					{
						label:
							'Configure Endpoint and Model',
						id:
							'configure'
					},
					{
						label:
							'Set API Key',
						id:
							'set-key'
					},
					{
						label:
							'Clear API Key',
						id:
							'clear-key'
					},
					{
						label:
							'Test Connection',
						id:
							'test'
					},
					{
						label:
							'Open Agent Settings',
						id:
							'settings'
					}
				];
				if (role === 'coding') {
					actions.splice(2, 0, {
						label: 'Migrate Legacy Coding API Key',
						id: 'migrate-key'
					});
				}


				const action =
					await vscode.window.showQuickPick(
						actions,
						{
							title:
								`Agent Studio: ${selected.label}`
						}
					);

				if (!action) {
					return;
				}

				if (
					action.id ===
					'settings'
				) {
					await vscode.commands.executeCommand(
						'workbench.action.openSettings',
						`agentStudio.agents.${role}`
					);

					return;
				}

				if (
					action.id ===
					'configure'
				) {
					const current =
						await service.getPublicProfile(
							role
						);

					const baseUrl =
						await vscode.window.showInputBox({
							title:
								`${selected.label}: Endpoint`,
							value:
								current.baseUrl,
							prompt:
								'OpenAI-compatible API base URL',
							ignoreFocusOut:
								true,
							validateInput:
								value =>
									validEndpoint(
										value.trim()
									)
										? undefined
										: 'Enter an HTTP(S) endpoint without embedded credentials, query or fragment.'
						});

					if (
						baseUrl ===
						undefined
					) {
						return;
					}

					const model =
						await vscode.window.showInputBox({
							title:
								`${selected.label}: Model`,
							value:
								current.model,
							prompt:
								'Exact model ID returned by /v1/models',
							ignoreFocusOut:
								true,
							validateInput:
								value =>
									value.trim()
										? undefined
										: 'Model ID is required.'
						});

					if (
						model ===
						undefined
					) {
						return;
					}

					const config =
						vscode.workspace.getConfiguration(
							'agentStudio'
						);

					await config.update(
						`agents.${role}.baseUrl`,
						baseUrl.trim().replace(/\/+$/, ''),
						vscode.ConfigurationTarget.Global
					);

					await config.update(
						`agents.${role}.model`,
						model.trim(),
						vscode.ConfigurationTarget.Global
					);

					vscode.window.showInformationMessage(
						`${selected.label} inference settings saved. Backend routing was not changed.`
					);

					return;
				}
				if (action.id === 'migrate-key') {
					const choice =
						await vscode.window.showWarningMessage(
							'Copy the existing Coding Agent API key into the new Coding profile? The old key will remain stored. Endpoint and model settings will not change.',
							{ modal: true },
							'Copy Credential'
						);

					if (choice !== 'Copy Credential') {
						return;
					}

					const result =
						await service.migrateLegacyCodingKey();

					const messages = {
						MIGRATED:
							'Legacy Coding Agent credential copied to the new Coding profile.',
						LEGACY_KEY_ABSENT:
							'No legacy Coding Agent credential was found.',
						NEW_KEY_EXISTS:
							'The new Coding Agent profile already has a credential. Nothing was overwritten.'
					};

					vscode.window.showInformationMessage(
						messages[result]
					);

					return;
				}


				if (
					action.id ===
					'set-key'
				) {
					const apiKey =
						await vscode.window.showInputBox({
							title:
								`${selected.label}: API Key`,
							password:
								true,
							ignoreFocusOut:
								true,
							prompt:
								'Stored separately in VS Code SecretStorage'
						});

					if (
						apiKey ===
						undefined
					) {
						return;
					}

					await service.setApiKey(
						role,
						apiKey
					);

					vscode.window.showInformationMessage(
						`${selected.label} API key stored.`
					);

					return;
				}

				if (
					action.id ===
					'clear-key'
				) {
					const choice =
						await vscode.window.showWarningMessage(
							`Clear ${selected.label} API key?`,
							{
								modal: true
							},
							'Clear API Key'
						);

					if (
						choice !==
						'Clear API Key'
					) {
						return;
					}

					await service.clearApiKey(
						role
					);

					vscode.window.showInformationMessage(
						`${selected.label} API key cleared.`
					);

					return;
				}

				if (
					action.id ===
					'test'
				) {
					const runtimeConfig =
						await service.getConfig(
							role
						);

					const result =
						await probeAgentConnection(
							runtimeConfig
						);

					const status =
						result.httpStatus
							? ` · HTTP ${result.httpStatus}`
							: '';

					const message =
						`${selected.label}: ${result.state}${status}`;

					if (
						result.state ===
						'CONNECTED'
					) {
						vscode.window.showInformationMessage(
							message
						);
					} else {
						vscode.window.showWarningMessage(
							message
						);
					}
				}
			} catch (error) {
				const message =
					error instanceof Error
						? error.message
						: 'Inference settings operation failed.';

				vscode.window.showErrorMessage(
					`Agent inference settings: ${message}`
				);
			}
		}
	);
}
