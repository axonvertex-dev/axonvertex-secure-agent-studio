import { probeAgentConnection } from './model/AgentConnectionProbe';
import { registerAgentInferenceCommands } from './model/AgentInferenceCommands';
import * as vscode from 'vscode';
import { OperatorWorkbenchViewProvider } from './operator/OperatorWorkbenchViewProvider';

import {
	runAgent
} from './agent/AgentLoop';

import {
	CodingAgentViewProvider
} from './ui/CodingAgentViewProvider';

import {
	ModelConfigService
} from './model/ModelConfig';

import {
	createChatCompletion
} from './model/OpenAICompatibleClient';


/*
 * ============================================================
 * DIRECT CODING-ASSISTANT SYSTEM PROMPT
 * ============================================================
 *
 * Used by the lightweight command-palette commands.
 *
 * The repository agent uses AgentLoop and its stronger
 * repository/tool/governance system prompt.
 */

const DIRECT_SYSTEM_PROMPT =
	`
You are Agent Studio Coding Agent.

You are a software engineering coding assistant.

Rules:

- Analyze only the code and context supplied to you.
- Never pretend you inspected files that were not supplied.
- Never claim files were modified unless tool evidence proves it.
- Never claim tests were executed unless tool evidence proves it.
- Identify bugs, risks, and implementation details precisely.
- Prefer minimal and maintainable changes.
- Do not invent repository structure.
- Distinguish static analysis from runtime verification.
- Never describe software as production ready without sufficient
  runtime and deployment evidence.
	`.trim();


/*
 * ============================================================
 * DIRECT MODEL CALL
 * ============================================================
 *
 * Model-neutral.
 *
 * Endpoint, model, API key, temperature, output limit and
 * timeout are resolved from ModelConfigService.
 */

async function callConfiguredModel(
	userPrompt: string,
	modelConfigService: ModelConfigService,
	signal?: AbortSignal
): Promise<string> {

	const config =
		await modelConfigService
			.getConfig();


	const response =
		await createChatCompletion(
			config,
			{
				messages: [
					{
						role:
							'system',

						content:
							DIRECT_SYSTEM_PROMPT
					},

					{
						role:
							'user',

						content:
							userPrompt
					}
				],

				signal
			}
		);


	const content =
		response
			.choices?.[0]
			?.message
			?.content;


	if (!content) {

		throw new Error(
			'Configured model returned no assistant content.'
		);
	}


	return content;
}


/*
 * ============================================================
 * GENERIC PROGRESS WRAPPER
 * ============================================================
 */

async function runWithProgress(
	prompt: string,
	modelConfigService: ModelConfigService
): Promise<string> {

	return await vscode.window.withProgress(
		{
			location:
				vscode.ProgressLocation.Notification,

			title:
				'Agent Studio: Coding Agent is reasoning...',

			cancellable:
				true
		},

		async (
			_progress,
			cancellationToken
		) => {

			const controller =
				new AbortController();


			const subscription =
				cancellationToken
					.onCancellationRequested(
						() => {

							controller.abort();
						}
					);


			try {

				return await callConfiguredModel(
					prompt,
					modelConfigService,
					controller.signal
				);

			} finally {

				subscription.dispose();
			}
		}
	);
}


/*
 * ============================================================
 * TEST MODEL CONNECTION
 * ============================================================
 */

async function testModelConnection(
    modelConfigService: ModelConfigService
): Promise<void> {
    const config =
        await modelConfigService.getConfig();

    const result =
        await probeAgentConnection(config);

    const suffix =
        result.httpStatus === undefined
            ? ''
            : ` (HTTP ${result.httpStatus})`;

    const message =
        `Coding Agent: ${result.state}${suffix}`;

    if (result.state === 'CONNECTED') {
        vscode.window.showInformationMessage(
            message
        );
    } else {
        vscode.window.showWarningMessage(
            message
        );
    }
}


/*
 * ============================================================
 * EXTENSION ACTIVATION
 * ============================================================
 */

export function activate(
	context: vscode.ExtensionContext
): void {

	console.log(
		'[AgentStudio] activate() called'
	);




	/*
	 * --------------------------------------------------------
	 * MODEL CONFIGURATION SERVICE
	 * --------------------------------------------------------
	 *
	 * One shared instance is used by:
	 *
	 * - sidebar Coding Agent
	 * - direct coding command
	 * - selected-code command
	 * - repository agent
	 *
	 * API keys are retrieved from VS Code SecretStorage.
	 */

	const modelConfigService =
		new ModelConfigService(
			context.secrets
		);


	/*
	 * --------------------------------------------------------
	 * OUTPUT CHANNEL
	 * --------------------------------------------------------
	 */

	const output =
		vscode.window.createOutputChannel(
			'Agent Studio Coding Agent'
		);


	context.subscriptions.push(
		output
	);


	/*
	 * --------------------------------------------------------
	 * AGENT STUDIO SIDEBAR
	 * --------------------------------------------------------
	 */

	const codingAgentViewProvider =
		new CodingAgentViewProvider(
			modelConfigService
		);


	const codingAgentViewRegistration =
		vscode.window.registerWebviewViewProvider(
			CodingAgentViewProvider.viewType,

			codingAgentViewProvider,

			{
				webviewOptions: {
					retainContextWhenHidden:
						true
				}
			}
		);


	context.subscriptions.push(
		codingAgentViewRegistration
	);

	/* 0.7D1: independent read-only operator inspector; existing coding agent stays unchanged. */
	const operatorWorkbench = new OperatorWorkbenchViewProvider();
	const operatorRegistration = vscode.window.registerWebviewViewProvider(
		OperatorWorkbenchViewProvider.viewType,
		operatorWorkbench,
		{ webviewOptions: { retainContextWhenHidden: true } },
	);
	const operatorRefresh = vscode.commands.registerCommand(
		'agentStudio.operator.refresh',
		() => operatorWorkbench.refresh(),
	);
	context.subscriptions.push(operatorRegistration, operatorRefresh);



	/*
	 * ========================================================
	 * COMMAND 1
	 * ASK CODING AGENT
	 * ========================================================
	 */

	const askCodingAgent =
		vscode.commands.registerCommand(
			'agentStudio.askCodingAgent',

			async () => {

				const task =
					await vscode.window.showInputBox({
						title:
							'Agent Studio Coding Agent',

						prompt:
							'Enter a coding task',

						placeHolder:
							'Example: Explain how to implement a FastAPI health endpoint'
					});


				if (!task) {

					return;
				}


				output.clear();
				output.show(true);


				try {

					const config =
						await modelConfigService
							.getConfig();


					output.appendLine(
						'=== Agent Studio Coding Agent ==='
					);

					output.appendLine(
						`Model: ${config.model}`
					);

					output.appendLine(
						`Endpoint: ${config.baseUrl}`
					);

					output.appendLine('');

					output.appendLine(
						'TASK'
					);

					output.appendLine(
						task
					);

					output.appendLine('');

					output.appendLine(
						'Thinking...'
					);

					output.appendLine('');


					const answer =
						await runWithProgress(
							task,
							modelConfigService
						);


					output.appendLine(
						'RESPONSE'
					);

					output.appendLine(
						'========'
					);

					output.appendLine(
						answer
					);

				} catch (error) {

					const message =
						error instanceof Error
							? error.message
							: String(error);


					output.appendLine('');

					output.appendLine(
						'ERROR'
					);

					output.appendLine(
						message
					);


					vscode.window.showErrorMessage(
						`Coding Agent failed: ${message}`
					);
				}
			}
		);


	/*
	 * ========================================================
	 * COMMAND 2
	 * ASK ABOUT SELECTED CODE
	 * ========================================================
	 */

	const askSelectedCode =
		vscode.commands.registerCommand(
			'agentStudio.askSelectedCode',

			async () => {

				const editor =
					vscode.window.activeTextEditor;


				if (!editor) {

					vscode.window.showWarningMessage(
						'Open a source file first.'
					);

					return;
				}


				const selection =
					editor.selection;


				if (
					selection.isEmpty
				) {

					vscode.window.showWarningMessage(
						'Select some code first.'
					);

					return;
				}


				const selectedCode =
					editor.document.getText(
						selection
					);


				const fileName =
					editor.document.fileName;


				const language =
					editor.document.languageId;


				const instruction =
					await vscode.window.showInputBox({
						title:
							'Agent Studio: Selected Code',

						prompt:
							'What should the Coding Agent do?',

						placeHolder:
							'Example: Find bugs and suggest a safer implementation'
					});


				if (!instruction) {

					return;
				}


				const prompt =
					`
CODING TASK

Instruction:
${instruction}

File:
${fileName}

Language:
${language}

Selected code:

\`\`\`${language}
${selectedCode}
\`\`\`

Analyze the supplied code and respond to the instruction.
					`.trim();


				output.clear();
				output.show(true);


				output.appendLine(
					'=== Agent Studio Coding Agent ==='
				);

				output.appendLine('');

				output.appendLine(
					`FILE: ${fileName}`
				);

				output.appendLine(
					`LANGUAGE: ${language}`
				);

				output.appendLine('');

				output.appendLine(
					`TASK: ${instruction}`
				);

				output.appendLine('');

				output.appendLine(
					'Thinking...'
				);

				output.appendLine('');


				try {

					const answer =
						await runWithProgress(
							prompt,
							modelConfigService
						);


					output.appendLine(
						'RESPONSE'
					);

					output.appendLine(
						'========'
					);

					output.appendLine(
						answer
					);

				} catch (error) {

					const message =
						error instanceof Error
							? error.message
							: String(error);


					output.appendLine('');

					output.appendLine(
						'ERROR'
					);

					output.appendLine(
						message
					);


					vscode.window.showErrorMessage(
						`Coding Agent failed: ${message}`
					);
				}
			}
		);


	/*
	 * ========================================================
	 * COMMAND 3
	 * AUTONOMOUS REPOSITORY AGENT
	 * ========================================================
	 */

	const repositoryAgent =
		vscode.commands.registerCommand(
			'agentStudio.inspectRepository',

			async () => {

				const folders =
					vscode.workspace.workspaceFolders;


				if (
					!folders ||
					folders.length === 0
				) {

					vscode.window.showWarningMessage(
						'Open a workspace folder first.'
					);

					return;
				}


				const task =
					await vscode.window.showInputBox({
						title:
							'Agent Studio Repository Agent',

						prompt:
							'Give the Coding Agent a repository task',

						placeHolder:
							'Example: Inspect this repository and find the health endpoint'
					});


				if (!task) {

					return;
				}


				output.clear();
				output.show(true);


				output.appendLine(
					'=== Agent Studio Repository Agent ==='
				);

				output.appendLine('');

				output.appendLine(
					`WORKSPACE: ${folders[0].uri.fsPath}`
				);

				output.appendLine('');

				output.appendLine(
					`TASK: ${task}`
				);

				output.appendLine('');

				output.appendLine(
					'AGENT ACTIVITY'
				);

				output.appendLine(
					'=============='
				);


				try {

					const result =
						await vscode.window.withProgress(
							{
								location:
									vscode.ProgressLocation.Notification,

								title:
									'Agent Studio: Coding Agent running...',

								cancellable:
									false
							},

							async () => {

								return await runAgent(
									task,

									{
										log:
											(
												message: string
											) => {

												output.appendLine(
													message
												);
											}
									},

									{
										modelConfig:
											modelConfigService
									}
								);
							}
						);


					output.appendLine('');

					output.appendLine(
						'FINAL RESPONSE'
					);

					output.appendLine(
						'=============='
					);

					output.appendLine(
						result
					);

				} catch (error) {

					const message =
						error instanceof Error
							? error.message
							: String(error);


					output.appendLine('');

					output.appendLine(
						`ERROR: ${message}`
					);


					vscode.window.showErrorMessage(
						`Repository Agent failed: ${message}`
					);
				}
			}
		);


	/*
	 * ========================================================
	 * COMMAND 4
	 * CONFIGURE MODEL
	 * ========================================================
	 */

	const configureModel =
		vscode.commands.registerCommand(
			'agentStudio.configureModel',

			async () => {

				try {

					const current =
						await modelConfigService
							.getConfig();


					const baseUrl =
						await vscode.window.showInputBox({
							title:
								'Agent Studio: Model Endpoint',

							prompt:
								'Enter the OpenAI-compatible API base URL',

							value:
								current.baseUrl,

							placeHolder:
								'http://localhost:8000/v1',

							ignoreFocusOut:
								true
						});


					if (
						baseUrl === undefined
					) {

						return;
					}


					const model =
						await vscode.window.showInputBox({
							title:
								'Agent Studio: Model Name',

							prompt:
								'Enter the model identifier exposed by the endpoint',

							value:
								current.model,

							placeHolder:
								'gemma-4-12b-it-qat',

							ignoreFocusOut:
								true
						});


					if (
						model === undefined
					) {

						return;
					}


					if (
						!baseUrl.trim() ||
						!model.trim()
					) {

						vscode.window.showErrorMessage(
							'Endpoint and model name cannot be empty.'
						);

						return;
					}


					const configuration =
						vscode.workspace
							.getConfiguration(
								'agentStudio'
							);


					await configuration.update(
						'agents.coding.baseUrl',
						baseUrl
							.trim()
							.replace(
								/\/+$/,
								''
							),
						vscode.ConfigurationTarget.Global
					);


					await configuration.update(
						'agents.coding.model',
						model.trim(),
						vscode.ConfigurationTarget.Global
					);


					vscode.window.showInformationMessage(
						`Agent Studio model configured: ${model.trim()}`
					);

				} catch (error) {

					const message =
						error instanceof Error
							? error.message
							: String(error);


					vscode.window.showErrorMessage(
						`Could not configure model: ${message}`
					);
				}
			}
		);


	/*
	 * ========================================================
	 * COMMAND 5
	 * SET API KEY
	 * ========================================================
	 */

	const setApiKey =
		vscode.commands.registerCommand(
			'agentStudio.setApiKey',

			async () => {

				const apiKey =
					await vscode.window.showInputBox({
						title:
							'Agent Studio: Set API Key',

						prompt:
							'Enter the API key for the configured model endpoint',

						password:
							true,

						ignoreFocusOut:
							true
					});


				if (
					apiKey === undefined
				) {

					return;
				}


				if (
					!apiKey.trim()
				) {

					vscode.window.showErrorMessage(
						'API key cannot be empty.'
					);

					return;
				}


				await modelConfigService
					.setApiKey(
						apiKey
					);


				vscode.window.showInformationMessage(
					'Agent Studio API key stored securely in VS Code SecretStorage.'
				);
			}
		);


	/*
	 * ========================================================
	 * COMMAND 6
	 * CLEAR API KEY
	 * ========================================================
	 */

	const clearApiKey =
		vscode.commands.registerCommand(
			'agentStudio.clearApiKey',

			async () => {

				const choice =
					await vscode.window.showWarningMessage(
						'Clear the Agent Studio model API key?',
						{
							modal:
								true
						},
						'Clear API Key'
					);


				if (
					choice !==
						'Clear API Key'
				) {

					return;
				}


				await modelConfigService
					.clearApiKey();


				vscode.window.showInformationMessage(
					'Agent Studio API key cleared.'
				);
			}
		);


	/*
	 * ========================================================
	 * COMMAND 7
	 * TEST MODEL CONNECTION
	 * ========================================================
	 */

	const testConnection =
		vscode.commands.registerCommand(
			'agentStudio.testModelConnection',

			async () => {

				try {

					await testModelConnection(
						modelConfigService
					);

				} catch (error) {

					const message =
						error instanceof Error
							? error.message
							: String(error);


					vscode.window.showErrorMessage(
						message
					);
				}
			}
		);


	/*
	 * ========================================================
	 * COMMAND 8
	 * OPEN MODEL SETTINGS
	 * ========================================================
	 */

	const openModelSettings =
		vscode.commands.registerCommand(
			'agentStudio.openModelSettings',

			async () => {

				await vscode.commands
					.executeCommand(
						'workbench.action.openSettings',
						'agentStudio.agents.coding'
					);
			}
		);


	/*
	 * ========================================================
	 * REGISTER DISPOSABLES
	 * ========================================================
	 */

context.subscriptions.push(
	registerAgentInferenceCommands(context.secrets)
);

	context.subscriptions.push(
		askCodingAgent,
		askSelectedCode,
		repositoryAgent,
		configureModel,
		setApiKey,
		clearApiKey,
		testConnection,
		openModelSettings
	);
}


/*
 * ============================================================
 * EXTENSION DEACTIVATION
 * ============================================================
 */

export function deactivate(): void {

	/*
	 * VS Code disposes registered resources through
	 * ExtensionContext subscriptions.
	 */
}
