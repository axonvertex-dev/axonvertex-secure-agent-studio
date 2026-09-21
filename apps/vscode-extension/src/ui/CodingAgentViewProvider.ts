import { probeAgentConnection } from '../model/AgentConnectionProbe';
import * as vscode from 'vscode';
import * as crypto from 'crypto';

import MarkdownIt = require('markdown-it');
import sanitizeHtml = require('sanitize-html');

import {
	runAgent
} from '../agent/AgentLoop';

import {
	ModelConfigService
} from '../model/ModelConfig';

import type {
	FileEditApprovalRequest,
	FileEditDecision
} from '../tools/ProposeFileEditTool';




type AgentState =
	| 'IDLE'
	| 'RUNNING'
	| 'COMPLETED'
	| 'STOPPED'
	| 'FAILED';


interface WebviewMessage {
	type: string;
	task?: string;
	approvalId?: string;
	decision?: FileEditDecision;
}


interface PendingApproval {
	id: string;
	request: FileEditApprovalRequest;
	signal: AbortSignal;
	resolve: (
		decision: FileEditDecision
	) => void;
	reject: (
		error: Error
	) => void;
	abortListener: () => void;
}


/*
 * ============================================================
 * CODING AGENT VIEW PROVIDER
 * ============================================================
 */

export class CodingAgentViewProvider
	implements vscode.WebviewViewProvider {


	public static readonly viewType =
		'agentStudio.codingAgent';


	public constructor(
		private readonly modelConfigService:
			ModelConfigService
	) {}


	/*
	 * ========================================================
	 * MARKDOWN ENGINE
	 * ========================================================
	 *
	 * HTML generated directly by the model is disabled here.
	 *
	 * Markdown output is subsequently passed through
	 * sanitize-html before entering the webview.
	 */
	private readonly markdown =
		new MarkdownIt({
			html: false,
			linkify: false,
			typographer: false,
			breaks: true
		});


	private view:
		vscode.WebviewView | undefined;


	private running =
		false;


	private abortController:
		AbortController | undefined;


	private conversationVersion =
		0;


	private approvalCounter =
		0;


	private pendingApproval:
		PendingApproval | undefined;


	/*
	 * ========================================================
	 * SAFE MARKDOWN RENDERING
	 * ========================================================
	 *
	 * Gemma Markdown
	 *      ↓
	 * markdown-it
	 *      ↓
	 * sanitize-html
	 *      ↓
	 * sanitized HTML
	 *      ↓
	 * VS Code webview
	 */

	private renderMarkdown(
		text: string
	): string {

		const rendered =
			this.markdown.render(
				text
			);


		return sanitizeHtml(
			rendered,
			{
				allowedTags: [
					'p',
					'br',

					'strong',
					'em',

					'code',
					'pre',

					'ul',
					'ol',
					'li',

					'blockquote',

					'h1',
					'h2',
					'h3',
					'h4',

					'hr'
				],

				allowedAttributes: {}
			}
		);
	}


	/*
	 * ========================================================
	 * RESOLVE VIEW
	 * ========================================================
	 */

	public resolveWebviewView(
		webviewView: vscode.WebviewView
	): void {

		this.view =
			webviewView;


		webviewView.webview.options = {
			enableScripts: true
		};


		webviewView.webview.html =
			this.getHtml(
				webviewView.webview
			);


		/*
		 * ----------------------------------------------------
		 * RECEIVE MESSAGES FROM WEBVIEW
		 * ----------------------------------------------------
		 */

		webviewView.webview.onDidReceiveMessage(
			async (
				message: WebviewMessage
			) => {

				switch (
					message.type
				) {

					case 'submitTask':

						await this.handleTask(
							message.task ?? ''
						);

						break;


					case 'stopAgent':

						this.stopAgent();

						break;


					case 'newConversation':

						this.newConversation();

						break;


					case 'webviewReady':

						await this.refreshModelStatus();

						break;


					case 'configureModel':

						await vscode.commands.executeCommand(
							'agentStudio.configureModel'
						);

						await this.refreshModelStatus();

						break;


					case 'approvalDecision':

						this.handleApprovalDecision(
							message.approvalId ?? '',
							message.decision
						);

						break;


					case 'reviewApprovalDiff':

						await this.reviewApprovalDiff(
							message.approvalId ?? ''
						);

						break;
				}
			}
		);


		webviewView.onDidDispose(
			() => {

				this.abortController
					?.abort();


				this.view =
					undefined;
			}
		);
	}


	/*
	 * ========================================================
	 * HANDLE USER TASK
	 * ========================================================
	 */

	private async handleTask(
		rawTask: string
	): Promise<void> {

		const task =
			rawTask.trim();


		if (!task) {
			return;
		}


		/*
		 * Prevent overlapping agent runs.
		 */
		if (this.running) {

			this.post({
				type: 'error',

				text:
					'Coding Agent is already running a task.'
			});

			return;
		}


		const folders =
			vscode.workspace.workspaceFolders;


		if (
			!folders ||
			folders.length === 0
		) {

			this.post({
				type: 'error',

				text:
					'Open a workspace folder before running the Coding Agent.'
			});

			return;
		}


		const conversationVersion =
			this.conversationVersion;


		const controller =
			new AbortController();


		this.abortController =
			controller;


		this.running =
			true;


		this.postState(
			'RUNNING'
		);


		/*
		 * ----------------------------------------------------
		 * USER MESSAGE
		 * ----------------------------------------------------
		 */

		this.post({
			type: 'user',
			text: task
		});


		/*
		 * ----------------------------------------------------
		 * ACTIVE WORKSPACE
		 * ----------------------------------------------------
		 */

		this.post({
			type: 'workspace',

			text:
				folders[0]
					.uri
					.fsPath
		});


		try {

			/*
			 * =================================================
			 * AUTONOMOUS AGENT LOOP
			 * =================================================
			 *
			 * Current tools:
			 *
			 * - list_files
			 * - search_code
			 * - read_file
			 * - propose_file_edit
			 * - run_test
			 * - git_diff
			 */

			const response =
				await runAgent(
					task,

					{
						log:
							(
								message: string
							) => {

								if (
									controller.signal.aborted ||
									conversationVersion !==
										this.conversationVersion
								) {

									return;
								}


								this.post({
									type:
										'activity',

									text:
										message
								});
							},

						requestFileEditApproval:
							(
								request:
									FileEditApprovalRequest
							) =>
								this.requestFileEditApproval(
									request,
									controller,
									conversationVersion
								)
					},

					{
						modelConfig:
							this.modelConfigService
					},

					controller.signal
				);


			if (
				controller.signal.aborted ||
				conversationVersion !==
					this.conversationVersion
			) {

				return;
			}


			/*
			 * -------------------------------------------------
			 * FINAL RESPONSE
			 * -------------------------------------------------
			 */

			this.post({
				type:
					'assistant',

				html:
					this.renderMarkdown(
						response ||
						'Task completed.'
					)
			});


			this.postState(
				'COMPLETED'
			);

		} catch (error) {

			const wasAborted =
				controller.signal.aborted ||
				(
					error instanceof Error &&
					error.name === 'AbortError'
				);


			if (
				conversationVersion !==
					this.conversationVersion
			) {

				return;
			}


			if (wasAborted) {

				this.postState(
					'STOPPED'
				);

				return;
			}


			const message =
				error instanceof Error
					? error.message
					: String(error);


			this.post({
				type:
					'error',

				text:
					message
			});


			this.postState(
				'FAILED'
			);

		} finally {

			if (
				this.abortController ===
					controller
			) {

				this.abortController =
					undefined;


				this.running =
					false;
			}


			this.post({
				type:
					'setBusy',

				value:
					false
			});
		}
	}



	/*
	 * ========================================================
	 * FILE EDIT APPROVAL
	 * ========================================================
	 */

	private createAbortError(): Error {
		const error =
			new Error(
				'Agent stopped by user.'
			);

		error.name =
			'AbortError';

		return error;
	}


	private requestFileEditApproval(
		request: FileEditApprovalRequest,
		controller: AbortController,
		conversationVersion: number
	): Promise<FileEditDecision> {
		const signal =
			controller.signal;

		if (
			signal.aborted ||
			conversationVersion !==
				this.conversationVersion
		) {
			return Promise.reject(
				this.createAbortError()
			);
		}

		if (
			this.pendingApproval
		) {
			return Promise.reject(
				new Error(
					'Another file edit approval is already pending.'
				)
			);
		}

		const approvalId =
			`approval-${Date.now()}-${++this.approvalCounter}`;

		return new Promise<FileEditDecision>(
			(
				resolve,
				reject
			) => {
				const abortListener =
					() => {
						if (
							this.pendingApproval?.id !==
								approvalId
						) {
							return;
						}

						this.pendingApproval =
							undefined;

						this.post({
							type:
								'approvalCancelled',

							approvalId
						});

						reject(
							this.createAbortError()
						);
					};

				this.pendingApproval =
				{
					id:
						approvalId,

					request,

					signal,

					resolve,

					reject,

					abortListener
				};

				signal.addEventListener(
					'abort',
					abortListener,
					{
						once: true
					}
				);

				console.log(
					'[AgentStudio][Approval] host created approval',
					{
						approvalId,
						path:
							request.path,
						hasView:
							Boolean(
								this.view
							)
					}
				);

				const approvalMessage =
					{
						type:
							'approvalRequest',

						approvalId,

						path:
							request.path,

						summary:
							request.summary
					};

				const targetView =
					this.view;

				if (
					!targetView
				) {

					this.pendingApproval =
						undefined;

					reject(
						new Error(
							'Agent Studio approval UI is unavailable.'
						)
					);

					return;
				}

				void targetView
					.webview
					.postMessage(
						approvalMessage
					)
					.then(
						(
							delivered
						) => {

							console.log(
								'[AgentStudio][Approval] approvalRequest delivery',
								{
									approvalId,
									delivered
								}
							);
						},
						(
							error
						) => {

							console.error(
								'[AgentStudio][Approval] approvalRequest delivery failed',
								error
							);
						}
					);

				if (
					signal.aborted
				) {
					abortListener();
				}
			}
		);
	}


	private handleApprovalDecision(
		approvalId: string,
		decision?: FileEditDecision
	): void {
		if (
			decision !== 'apply' &&
			decision !== 'reject'
		) {
			return;
		}

		const pending =
			this.pendingApproval;

		if (
			!pending ||
			pending.id !==
				approvalId
		) {
			return;
		}

		pending.signal.removeEventListener(
			'abort',
			pending.abortListener
		);

		this.pendingApproval =
			undefined;

		this.post({
			type:
				'approvalResolved',

			approvalId,

			decision
		});

		pending.resolve(
			decision
		);
	}


	private async reviewApprovalDiff(
		approvalId: string
	): Promise<void> {
		const pending =
			this.pendingApproval;

		if (
			!pending ||
			pending.id !==
				approvalId
		) {
			return;
		}

		await vscode.commands.executeCommand(
			'vscode.diff',
			pending.request.originalUri,
			pending.request.proposedUri,
			`Agent Studio Proposal: ${pending.request.path}`,
			{
				preview:
					true
			}
		);
	}

	/*
	 * ========================================================
	 * STOP AGENT
	 * ========================================================
	 */

	private stopAgent(): void {

		if (
			!this.running ||
			!this.abortController ||
			this.abortController.signal.aborted
		) {

			return;
		}


		this.abortController.abort();


		this.postState(
			'STOPPED'
		);
	}


	/*
	 * ========================================================
	 * NEW CONVERSATION
	 * ========================================================
	 */

	private newConversation(): void {

		this.conversationVersion++;


		if (
			this.abortController &&
			!this.abortController.signal.aborted
		) {

			this.abortController.abort();
		}


		this.post({
			type:
				'clearConversation'
		});


		this.postState(
			'IDLE'
		);


		if (!this.running) {

			this.post({
				type:
					'setBusy',

				value:
					false
			});
		}
	}


	/*
	 * ========================================================
	 * POST MESSAGE TO WEBVIEW
	 * ========================================================
	 */

	private async refreshModelStatus():
	Promise<void> {
	let model = 'Not configured';

	try {
		const config =
			await this.modelConfigService.getConfig();

		model = config.model;

		this.post({
			type: 'modelStatus',
			model,
			connected: undefined
		});

		const result =
			await probeAgentConnection(config);

		this.post({
			type: 'modelStatus',
			model,
			connected: result.state === 'CONNECTED'
		});
	} catch {
		this.post({
			type: 'modelStatus',
			model,
			connected: false
		});
	}
}

private post(
		message: unknown
	): void {

		void this.view
			?.webview
			.postMessage(
				message
			);
	}


	/*
	 * ========================================================
	 * AGENT STATE
	 * ========================================================
	 */

	private postState(
		state: AgentState
	): void {

		this.post({
			type:
				'state',

			state
		});


		if (
			state === 'RUNNING'
		) {

			this.post({
				type:
					'setBusy',

				value:
					true
			});
		}
	}


	/*
	 * ========================================================
	 * WEBVIEW HTML
	 * ========================================================
	 */

	private getHtml(
		webview: vscode.Webview
	): string {

		const nonce =
			crypto
				.randomBytes(16)
				.toString('base64');


		const csp =
			[
				"default-src 'none'",

				`style-src ${webview.cspSource} 'unsafe-inline'`,

				`script-src 'nonce-${nonce}'`
			]
				.join('; ');


		return /* html */ `
<!DOCTYPE html>

<html lang="en">

<head>

	<meta charset="UTF-8">

	<meta
		name="viewport"
		content="width=device-width, initial-scale=1.0"
	>

	<meta
		http-equiv="Content-Security-Policy"
		content="${csp}"
	>

	<title>
		Agent Studio Coding Agent
	</title>


	<style>

		/*
		 * ====================================================
		 * ROOT
		 * ====================================================
		 */

		:root {
			color-scheme:
				light dark;
		}


		* {
			box-sizing:
				border-box;
		}


		html,
		body {

			padding:
				0;

			margin:
				0;

			width:
				100%;

			height:
				100%;


			background:
				var(
					--vscode-sideBar-background
				);


			color:
				var(
					--vscode-sideBar-foreground
				);


			font-family:
				var(
					--vscode-font-family
				);


			font-size:
				var(
					--vscode-font-size
				);
		}


		body {

			display:
				flex;

			flex-direction:
				column;

			overflow:
				hidden;
		}


		/*
		 * ====================================================
		 * HEADER
		 * ====================================================
		 */

		.header {

			padding:
				12px;


			border-bottom:
				1px solid
				var(
					--vscode-panel-border
				);
		}


		.brand {

			font-weight:
				700;

			font-size:
				14px;

			letter-spacing:
				0.2px;
		}


		.modelRow {

			display:
				flex;

			align-items:
				center;

			justify-content:
				space-between;


			margin-top:
				8px;


			color:
				var(
					--vscode-descriptionForeground
				);


			font-size:
				11px;
		}


		/*
		 * ====================================================
		 * STATUS
		 * ====================================================
		 */

		.status {

			display:
				flex;

			align-items:
				center;

			gap:
				6px;
		}


		.statusDot {

			width:
				7px;

			height:
				7px;

			border-radius:
				50%;


			background:
				var(
					--vscode-descriptionForeground
				);
		}


		.statusDot.running {

			background:
				var(
					--vscode-charts-yellow
				);
		}


		.statusDot.completed {

			background:
				var(
					--vscode-testing-iconPassed
				);
		}


		.statusDot.stopped {

			background:
				var(
					--vscode-charts-orange,
					var(
						--vscode-descriptionForeground
					)
				);
		}


		.statusDot.failed {

			background:
				var(
					--vscode-testing-iconFailed
				);
		}


		/*
		 * ====================================================
		 * WORKSPACE
		 * ====================================================
		 */

		.workspace {

			padding:
				7px 12px;


			font-size:
				10px;


			color:
				var(
					--vscode-descriptionForeground
				);


			border-bottom:
				1px solid
				var(
					--vscode-panel-border
				);


			white-space:
				nowrap;

			overflow:
				hidden;

			text-overflow:
				ellipsis;
		}


		/*
		 * ====================================================
		 * CHAT AREA
		 * ====================================================
		 */

		.chat {

			flex:
				1;

			overflow-y:
				auto;


			padding:
				12px;
		}


		.message {

			margin-bottom:
				16px;
		}


		.messageLabel {

			font-size:
				10px;

			font-weight:
				700;

			text-transform:
				uppercase;


			color:
				var(
					--vscode-descriptionForeground
				);


			margin-bottom:
				6px;
		}


		.messageBody {

			word-break:
				break-word;

			line-height:
				1.5;
		}


		/*
		 * ====================================================
		 * USER MESSAGE
		 * ====================================================
		 */

		.userMessage {

			padding:
				9px 10px;


			white-space:
				pre-wrap;


			background:
				var(
					--vscode-input-background
				);


			border:
				1px solid
				var(
					--vscode-input-border,
					transparent
				);


			border-radius:
				5px;
		}


		/*
		 * ====================================================
		 * ASSISTANT MARKDOWN
		 * ====================================================
		 */

		.assistantMessage {

			padding:
				4px 0;
		}


		.assistantMessage p {

			margin:
				0 0 10px 0;

			line-height:
				1.55;
		}


		.assistantMessage p:last-child {

			margin-bottom:
				0;
		}


		.assistantMessage h1,
		.assistantMessage h2,
		.assistantMessage h3,
		.assistantMessage h4 {

			margin:
				14px 0 8px 0;

			line-height:
				1.3;
		}


		.assistantMessage h1 {
			font-size:
				1.35em;
		}


		.assistantMessage h2 {
			font-size:
				1.22em;
		}


		.assistantMessage h3 {
			font-size:
				1.12em;
		}


		.assistantMessage h4 {
			font-size:
				1.05em;
		}


		/*
		 * ----------------------------------------------------
		 * INLINE CODE
		 * ----------------------------------------------------
		 */

		.assistantMessage code {

			font-family:
				var(
					--vscode-editor-font-family
				);


			font-size:
				0.95em;


			background:
				var(
					--vscode-textCodeBlock-background
				);


			padding:
				1px 4px;


			border-radius:
				3px;
		}


		/*
		 * ----------------------------------------------------
		 * CODE BLOCKS
		 * ----------------------------------------------------
		 */

		.assistantMessage pre {

			overflow-x:
				auto;


			padding:
				10px;


			margin:
				10px 0;


			background:
				var(
					--vscode-textCodeBlock-background
				);


			border-radius:
				4px;
		}


		.assistantMessage pre code {

			padding:
				0;


			background:
				transparent;


			white-space:
				pre;


			font-size:
				11px;
		}


		/*
		 * ----------------------------------------------------
		 * LISTS
		 * ----------------------------------------------------
		 */

		.assistantMessage ul,
		.assistantMessage ol {

			padding-left:
				22px;


			margin:
				8px 0 10px 0;
		}


		.assistantMessage li {

			margin:
				3px 0;
		}


		/*
		 * ----------------------------------------------------
		 * BLOCKQUOTE
		 * ----------------------------------------------------
		 */

		.assistantMessage blockquote {

			margin:
				10px 0;


			padding:
				2px 0 2px 10px;


			border-left:
				2px solid
				var(
					--vscode-textBlockQuote-border
				);


			color:
				var(
					--vscode-textBlockQuote-foreground
				);
		}


		.assistantMessage hr {

			border:
				0;


			border-top:
				1px solid
				var(
					--vscode-panel-border
				);


			margin:
				14px 0;
		}


		/*
		 * ====================================================
		 * AGENT ACTIVITY
		 * ====================================================
		 */

		.activityBlock {

			margin:
				8px 0 16px 0;


			padding:
				8px;


			border-left:
				2px solid
				var(
					--vscode-focusBorder
				);


			background:
				var(
					--vscode-textCodeBlock-background
				);
		}


		.activityTitle {

			font-size:
				10px;

			font-weight:
				700;

			text-transform:
				uppercase;


			margin-bottom:
				6px;


			color:
				var(
					--vscode-descriptionForeground
				);
		}


		.activityItem {

			font-family:
				var(
					--vscode-editor-font-family
				);


			font-size:
				11px;


			white-space:
				pre-wrap;


			word-break:
				break-word;


			padding:
				2px 0;
		}
		
		
		


		.activityTurn {
				margin:
					8px 0 5px 0;

				font-size:
					10px;

				color:
					var(
						--vscode-descriptionForeground
					);
			}


			.toolCard {

				margin:
					6px 0;

				padding:
					8px;

				border:
					1px solid
					var(
						--vscode-panel-border
					);

				border-radius:
					5px;

				background:
					var(
						--vscode-editor-background
					);
			}


			.toolHeader {

				display:
					flex;

				align-items:
					center;

				justify-content:
					space-between;

				gap:
					8px;
			}


			.toolName {

				font-size:
					11px;

				font-weight:
					700;

				text-transform:
					uppercase;
			}


			.toolStatus {

				font-size:
					10px;

				color:
					var(
						--vscode-descriptionForeground
					);
			}


			.toolStatus.running {

				color:
					var(
						--vscode-charts-yellow
					);
			}


			.toolStatus.success {

				color:
					var(
						--vscode-testing-iconPassed
					);
			}


			.toolStatus.failed {

				color:
					var(
						--vscode-testing-iconFailed
					);
			}


			.toolArguments {

				margin-top:
					6px;

				font-family:
					var(
						--vscode-editor-font-family
					);

				font-size:
					10px;

				color:
					var(
						--vscode-descriptionForeground
					);

				white-space:
					pre-wrap;

				word-break:
					break-word;
			}



		/*
		 * ====================================================
		 * APPROVAL CARD
		 * ====================================================
		 */

		.approvalCard {

			margin-top:
				9px;

			padding:
				9px;

			border:
				1px solid
				var(
					--vscode-inputValidation-warningBorder,
					--vscode-panel-border
				);

			border-radius:
				5px;

			background:
				var(
					--vscode-editorWidget-background,
					--vscode-editor-background
				);
		}


		.approvalTitle {

			font-size:
				10px;

			font-weight:
				700;

			text-transform:
				uppercase;

			color:
				var(
					--vscode-inputValidation-warningForeground,
					--vscode-foreground
				);
		}


		.approvalPath {

			margin-top:
				6px;

			font-family:
				var(
					--vscode-editor-font-family
				);

			font-size:
				11px;
		}


		.approvalSummary {

			margin-top:
				6px;

			font-size:
				10px;

			line-height:
				1.4;

			color:
				var(
					--vscode-descriptionForeground
				);
		}


		.approvalStatus {

			margin-top:
				7px;

			font-size:
				10px;

			font-weight:
				700;
		}


		.approvalActions {

			display:
				flex;

			flex-wrap:
				wrap;

			gap:
				6px;

			margin-top:
				8px;
		}


		.approvalActions button {

			padding:
				5px 8px;

			font-size:
				10px;
		}


		.approvalApply {

			background:
				var(
					--vscode-testing-iconPassed,
					--vscode-button-background
				);
		}


		.approvalReject {

			background:
				var(
					--vscode-testing-iconFailed,
					--vscode-button-background
				);
		}


		.toolStatus.waiting,
		.toolStatus.notApplied {

			color:
				var(
					--vscode-charts-orange,
					--vscode-charts-yellow
				);
		}

		/*
		 * ====================================================
		 * ERROR
		 * ====================================================
		 */

		.errorMessage {

			white-space:
				pre-wrap;


			color:
				var(
					--vscode-errorForeground
				);
		}


		/*
		 * ====================================================
		 * EMPTY STATE
		 * ====================================================
		 */

		.empty {

			color:
				var(
					--vscode-descriptionForeground
				);


			line-height:
				1.5;
		}


		/*
		 * ====================================================
		 * COMPOSER
		 * ====================================================
		 */

		.composer {

			padding:
				10px;


			border-top:
				1px solid
				var(
					--vscode-panel-border
				);


			background:
				var(
					--vscode-sideBar-background
				);
		}


		textarea {

			width:
				100%;


			min-height:
				72px;


			max-height:
				180px;


			resize:
				vertical;


			padding:
				8px;


			color:
				var(
					--vscode-input-foreground
				);


			background:
				var(
					--vscode-input-background
				);


			border:
				1px solid
				var(
					--vscode-input-border,
					transparent
				);


			outline:
				none;


			font-family:
				var(
					--vscode-font-family
				);


			font-size:
				var(
					--vscode-font-size
				);
		}


		textarea:focus {

			border-color:
				var(
					--vscode-focusBorder
				);
		}


		.actions {

			display:
				flex;


			align-items:
				center;


			justify-content:
				space-between;


			gap:
				8px;


			margin-top:
				8px;
		}


		.rightActions {

			display:
				flex;

			gap:
				6px;
		}


		button {

			border:
				0;


			padding:
				6px 14px;


			color:
				var(
					--vscode-button-foreground
				);


			background:
				var(
					--vscode-button-background
				);


			cursor:
				pointer;
		}


		button:hover {

			background:
				var(
					--vscode-button-hoverBackground
				);
		}


		button.secondary {

			color:
				var(
					--vscode-button-secondaryForeground
				);


			background:
				var(
					--vscode-button-secondaryBackground
				);
		}


		button.secondary:hover {

			background:
				var(
					--vscode-button-secondaryHoverBackground
				);
		}


		button:disabled {

			opacity:
				0.5;


			cursor:
				default;
		}

	

		/* Model configuration status */

		#modelName {
			font-family:
				var(--vscode-editor-font-family);

			font-size:
				11px;

			font-weight:
				600;
		}


		.modelConnection {
			margin-left:
				6px;

			font-size:
				10px;
		}


		.modelConnection.connected {
			color:
				var(--vscode-testing-iconPassed);
		}


		.modelConnection.disconnected {
			color:
				var(--vscode-testing-iconFailed);
		}


		.modelConnection.checking {
			color:
				var(--vscode-descriptionForeground);
		}


		.modelConfigButton {
			margin-left:
				5px;

			min-width:
				24px;

			padding:
				2px 5px;

			border:
				1px solid transparent;

			border-radius:
				4px;

			background:
				transparent;

			color:
				var(--vscode-foreground);

			cursor:
				pointer;
		}


		.modelConfigButton:hover {
			background:
				var(--vscode-toolbar-hoverBackground);

			border-color:
				var(--vscode-panel-border);
		}


	</style>

</head>


<body>


	<!-- =====================================================
	     HEADER
	     ===================================================== -->

	<div class="header">

		<div class="brand">
			Coding Agent
		</div>


		<div class="modelRow">

			<div>
				<span id="modelName">Loading model...</span>
<span id="modelConnection" class="modelConnection checking">● Checking</span>
<button
    id="configureModelButton"
    class="modelConfigButton"
    title="Configure model"
    aria-label="Configure model"
>⚙</button>
			</div>


			<div class="status">

				<div
					id="statusDot"
					class="statusDot"
				></div>


				<span
					id="statusText"
				>
					Idle
				</span>

			</div>

		</div>

	</div>


	<!-- =====================================================
	     WORKSPACE
	     ===================================================== -->

	<div
		id="workspace"
		class="workspace"
	>
		No active task
	</div>


	<!-- =====================================================
	     CHAT
	     ===================================================== -->

	<div
		id="chat"
		class="chat"
	>

		<div
			id="empty"
			class="empty"
		>
			Ask the Coding Agent to inspect,
			explain, modify, test, or verify
			the current repository.
		</div>

	</div>


	<!-- =====================================================
	     COMPOSER
	     ===================================================== -->

	<div class="composer">

		<textarea
			id="prompt"
			placeholder="Ask Coding Agent..."
		></textarea>


		<div class="actions">

			<button
				id="newConversation"
				class="secondary"
			>
				New
			</button>


			<div class="rightActions">

				<button
					id="stop"
					class="secondary"
					disabled
				>
					Stop
				</button>


				<button id="send">
					Send
				</button>

			</div>

		</div>

	</div>


	<!-- =====================================================
	     WEBVIEW SCRIPT
	     ===================================================== -->

	<script nonce="${nonce}">

		(() => {

		const vscode =
			acquireVsCodeApi();


		const chat =
			document.getElementById(
				'chat'
			);


		const promptInput =
			document.getElementById(
				'prompt'
			);


		const sendButton =
			document.getElementById(
				'send'
			);


		const stopButton =
			document.getElementById(
				'stop'
			);


		const newConversationButton =
			document.getElementById(
				'newConversation'
			);


		const empty =
			document.getElementById(
				'empty'
			);


		const statusText =
			document.getElementById(
				'statusText'
			);


		const statusDot =
			document.getElementById(
				'statusDot'
			);


		const workspace =
			document.getElementById(
				'workspace'
			);


		const modelName =
			document.getElementById(
				'modelName'
			);


		const modelConnection =
			document.getElementById(
				'modelConnection'
			);


		const configureModelButton =
			document.getElementById(
				'configureModelButton'
			);


		let currentActivityBlock =
			null;


		const pendingToolCards =
			[];


		const approvalCards =
			new Map();


		/*
		 * ====================================================
		 * SCROLL
		 * ====================================================
		 */

		function scrollBottom() {

			chat.scrollTop =
				chat.scrollHeight;
		}


		/*
		 * ====================================================
		 * EMPTY STATE
		 * ====================================================
		 */

		function showEmpty() {

			if (
				document.getElementById(
					'empty'
				)
			) {

				return;
			}


			const emptyState =
				document.createElement(
					'div'
				);


			emptyState.id =
				'empty';


			emptyState.className =
				'empty';


			emptyState.textContent =
				'Ask the Coding Agent to inspect, explain, modify, test, or verify the current repository.';


			chat.appendChild(
				emptyState
			);
		}


		function clearEmpty() {

			const currentEmpty =
				document.getElementById(
					'empty'
				);


			if (currentEmpty) {

				currentEmpty.remove();
			}
		}


		function clearConversation() {

			chat.textContent =
				'';


			currentActivityBlock =
				null;


			pendingToolCards.length =
				0;


			approvalCards.clear();


			workspace.textContent =
				'No active task';


			workspace.title =
				'';


			promptInput.value =
				'';


			showEmpty();


			scrollBottom();
		}


		/*
		 * ====================================================
		 * PLAIN TEXT MESSAGE
		 * ====================================================
		 */

		function addMessage(
			label,
			text,
			className
		) {

			clearEmpty();


			currentActivityBlock =
				null;


			const wrapper =
				document.createElement(
					'div'
				);


			wrapper.className =
				'message';


			const labelElement =
				document.createElement(
					'div'
				);


			labelElement.className =
				'messageLabel';


			labelElement.textContent =
				label;


			const body =
				document.createElement(
					'div'
				);


			body.className =
				'messageBody ' +
				className;


			body.textContent =
				typeof text === 'string'
					? text
					: '';


			wrapper.appendChild(
				labelElement
			);


			wrapper.appendChild(
				body
			);


			chat.appendChild(
				wrapper
			);


			scrollBottom();
		}


		/*
		 * ====================================================
		 * SANITIZED HTML ASSISTANT MESSAGE
		 * ====================================================
		 */

		function addHtmlMessage(
			label,
			html,
			className
		) {

			clearEmpty();


			currentActivityBlock =
				null;


			const wrapper =
				document.createElement(
					'div'
				);


			wrapper.className =
				'message';


			const labelElement =
				document.createElement(
					'div'
				);


			labelElement.className =
				'messageLabel';


			labelElement.textContent =
				label;


			const body =
				document.createElement(
					'div'
				);


			body.className =
				'messageBody ' +
				className;


			/*
			 * The extension host has already converted:
			 *
			 * Markdown
			 *   -> markdown-it
			 *   -> sanitize-html
			 *
			 * before this message reaches the webview.
			 */

			body.innerHTML =
				typeof html === 'string'
					? html
					: '';


			wrapper.appendChild(
				labelElement
			);


			wrapper.appendChild(
				body
			);


			chat.appendChild(
				wrapper
			);


			scrollBottom();
		}


		/*
		 * ====================================================
		 * AGENT ACTIVITY
		 * ====================================================
		 */


		function formatToolName(
			toolName
		) {

			switch (
				toolName
			) {

				case 'list_files':
					return 'LIST FILES';

				case 'search_code':
					return 'SEARCH CODE';

				case 'read_file':
					return 'READ FILE';

				case 'create_file':
					return 'CREATE FILE';

				case 'propose_file_edit':
					return 'PROPOSE EDIT';

				case 'run_test':
					return 'RUN TEST';

				case 'runtime_smoke_test':

					return 'RUNTIME SMOKE TEST';


				case 'git_diff':
					return 'GIT DIFF';

				default:

					return toolName
						.replaceAll(
							'_',
							' '
						)
						.toUpperCase();
			}
		}


		function formatToolArguments(
			toolName,
			rawArguments
		) {

			if (!rawArguments) {
				return '';
			}


			try {

				const args =
					JSON.parse(
						rawArguments
					);


				switch (
					toolName
				) {

					case 'read_file':

						return args.path
							? String(
								args.path
							)
							: '';


					case 'list_files':

						return args.pattern
							? String(
								args.pattern
							)
							: 'Repository';


					case 'search_code': {

						const parts =
							[];


						if (args.query) {

							parts.push(
								'Query: ' +
								String(
									args.query
								)
							);
						}


						if (args.glob) {

							parts.push(
								'Files: ' +
								String(
									args.glob
								)
							);
						}


						return parts.join(
							'\\n'
						);
					}


					case 'create_file':
					case 'propose_file_edit':

						return args.path
							? String(
								args.path
							)
							: '';


					case 'run_test': {

						const parts =
							[];


						if (args.type) {

							parts.push(
								String(
									args.type
								)
							);
						}


						if (args.path) {

							parts.push(
								String(
									args.path
								)
							);
						}


						if (args.module) {

							parts.push(

								String(

									args.module

								)

							);

						}


						return parts.join(
							' · '
						);
					}


					case 'runtime_smoke_test': {

	const checkCount =
		Array.isArray(
			args.checks
		)
			? args.checks.length
			: 0;


	const parts =
		[];


	if (args.app) {

		parts.push(

			String(

				args.app

			)

		);

	}


	parts.push(

		String(

			checkCount

		) +

		' HTTP checks'

	);


	return parts.join(

		' · '

	);
}


case 'git_diff':

						return args.path
							? String(
								args.path
							)
							: 'Repository';


					default:

						return JSON.stringify(
							args,
							null,
							2
						);
				}

			} catch {

				return rawArguments;
			}
		}


		function addActivity(
	text
) {

	clearEmpty();


	/*
	 * ========================================================
	 * CREATE ACTIVITY CONTAINER
	 * ========================================================
	 */

	if (
		!currentActivityBlock
	) {

		currentActivityBlock =
			document.createElement(
				'div'
			);


		currentActivityBlock.className =
			'activityBlock';


		const title =
			document.createElement(
				'div'
			);


		title.className =
			'activityTitle';


		title.textContent =
			'Agent Activity';


		currentActivityBlock.appendChild(
			title
		);


		chat.appendChild(
			currentActivityBlock
		);
	}


	/*
	 * ========================================================
	 * AGENT TURN
	 * ========================================================
	 *
	 * Incoming:
	 *
	 * Agent turn 1/10
	 */

	const turnMatch =
		text.match(
			/^Agent turn\\s+(\\d+)\\/(\\d+)$/
		);


	if (
		turnMatch
	) {

		const turn =
			document.createElement(
				'div'
			);


		turn.className =
			'activityTurn';


		turn.textContent =
			'Turn ' +
			turnMatch[1] +
			' of ' +
			turnMatch[2];


		currentActivityBlock.appendChild(
			turn
		);


		scrollBottom();

		return;
	}


	/*
	 * ========================================================
	 * TOOL START
	 * ========================================================
	 *
	 * Incoming examples:
	 *
	 * → read_file({"path":"app.py"})
	 *
	 * → list_files({"pattern":"*"})
	 */

	const toolStartMatch =
		text.match(
			/^→\\s+([a-zA-Z0-9_]+)\\((.*)\\)$/
		);


	if (
		toolStartMatch
	) {

		const toolName =
			toolStartMatch[1];


		const rawArguments =
			toolStartMatch[2];


		/*
		 * ----------------------------------------------------
		 * CARD
		 * ----------------------------------------------------
		 */

		const card =
			document.createElement(
				'div'
			);


		card.className =
			'toolCard';


		/*
		 * ----------------------------------------------------
		 * HEADER
		 * ----------------------------------------------------
		 */

		const header =
			document.createElement(
				'div'
			);


		header.className =
			'toolHeader';


		/*
		 * Tool name
		 */
		const name =
			document.createElement(
				'div'
			);


		name.className =
			'toolName';


		name.textContent =
			formatToolName(
				toolName
			);


		/*
		 * Tool status
		 */
		const status =
			document.createElement(
				'div'
			);


		status.className =
			'toolStatus running';


		status.textContent =
			'RUNNING';


		header.appendChild(
			name
		);


		header.appendChild(
			status
		);


		card.appendChild(
			header
		);


		/*
		 * ----------------------------------------------------
		 * TOOL ARGUMENTS
		 * ----------------------------------------------------
		 */

		const formattedArguments =
			formatToolArguments(
				toolName,
				rawArguments
			);


		if (
			formattedArguments
		) {

			const args =
				document.createElement(
					'div'
				);


			args.className =
				'toolArguments';


			args.textContent =
				formattedArguments;


			card.appendChild(
				args
			);
		}


		/*
		 * Add card to activity block.
		 */

		currentActivityBlock.appendChild(
			card
		);


		/*
		 * Remember the card so a later:
		 *
		 * ✓ read_file
		 *
		 * can mark this exact card PASS.
		 */

		pendingToolCards.push({
			toolName,
			status,
			card
		});


		scrollBottom();

		return;
	}


	/*
	 * ========================================================
	 * TOOL SUCCESS
	 * ========================================================
	 *
	 * Incoming:
	 *
	 * ✓ read_file
	 */

	const toolSuccessMatch =
		text.match(
			/^✓\\s+([a-zA-Z0-9_]+)$/
		);


	if (
		toolSuccessMatch
	) {

		const toolName =
			toolSuccessMatch[1];


		/*
		 * Search backwards because the latest invocation
		 * of a tool is the one that should be completed.
		 */

		for (
			let index =
				pendingToolCards.length - 1;

			index >= 0;

			index--
		) {

			const pending =
				pendingToolCards[index];


			if (
				pending.toolName ===
				toolName
			) {

				pending.status.className =
					'toolStatus success';


				pending.status.textContent =
					'PASS';


				pendingToolCards.splice(
					index,
					1
				);


				scrollBottom();

				return;
			}
		}
	}


	/*
	 * ========================================================
	 * TOOL FAILURE
	 * ========================================================
	 *
	 * This also prepares the UI for future AgentLoop
	 * failure logging such as:
	 *
	 * ✗ run_test
	 */

	const toolFailureMatch =
		text.match(
			/^✗\\s+([a-zA-Z0-9_]+)(?:\\s*:\\s*(.*))?$/
		);


	if (
		toolFailureMatch
	) {

		const toolName =
			toolFailureMatch[1];


		const failureMessage =
			toolFailureMatch[2] || 'FAILED';


		for (
			let index =
				pendingToolCards.length - 1;

			index >= 0;

			index--
		) {

			const pending =
				pendingToolCards[index];


			if (
				pending.toolName ===
				toolName
			) {

				pending.status.className =
					'toolStatus failed';


				pending.status.textContent =
					'FAILED';


				const detail =
					document.createElement(
						'div'
					);


				detail.className =
					'toolArguments';


				detail.textContent =
					failureMessage;


				pending.card.appendChild(
					detail
				);


				pendingToolCards.splice(
					index,
					1
				);


				scrollBottom();

				return;
			}
		}
	}



	/*
	 * ========================================================
	 * TOOL NOT APPLIED
	 * ========================================================
	 */

	const notAppliedMatch =
		text.match(
			/^↷\\s+([a-zA-Z0-9_]+)(?:\\s*:\\s*(.*))?$/
		);


	if (
		notAppliedMatch
	) {

		const toolName =
			notAppliedMatch[1];


		const message =
			notAppliedMatch[2] ||
			'Change was not applied.';


		if (
			markToolNotApplied(
				toolName,
				message
			)
		) {

			return;
		}
	}

	/*
	 * ========================================================
	 * FALLBACK
	 * ========================================================
	 *
	 * Do not discard unknown AgentLoop messages.
	 */

	const item =
		document.createElement(
			'div'
		);


	item.className =
		'activityItem';


	item.textContent =
		typeof text === 'string'
			? text
			: '';


	currentActivityBlock.appendChild(
		item
	);


	scrollBottom();
}


		/*
		 * ====================================================
		 * APPROVAL UI
		 * ====================================================
		 */

		function findPendingTool(
			toolName
		) {

			for (
				let index =
					pendingToolCards.length - 1;

				index >= 0;

				index--
			) {

				if (
					pendingToolCards[index]
						.toolName === toolName
				) {

					return pendingToolCards[index];
				}
			}


			return undefined;
		}


		/*
		 * ====================================================
		 * ENSURE ACTIVITY BLOCK
		 * ====================================================
		 *
		 * Approval requests can arrive directly from the
		 * extension host while a tool is waiting.
		 *
		 * addApprovalRequest() must therefore be able to
		 * guarantee that an Agent Activity container exists.
		 */

		function ensureActivityBlock() {

			clearEmpty();


			if (
				currentActivityBlock
			) {

				return currentActivityBlock;
			}


			currentActivityBlock =
				document.createElement(
					'div'
				);


			currentActivityBlock.className =
				'activityBlock';


			const title =
				document.createElement(
					'div'
				);


			title.className =
				'activityTitle';


			title.textContent =
				'Agent Activity';


			currentActivityBlock.appendChild(
				title
			);


			chat.appendChild(
				currentActivityBlock
			);


			scrollBottom();


			return currentActivityBlock;
		}


		function addApprovalRequest(
			message
		) {

			clearEmpty();


			ensureActivityBlock();


			const approvalId =
				String(
					message.approvalId ||
					''
				);


			if (!approvalId) {
				return;
			}


			const pendingTool =
				findPendingTool(
					'create_file'
				) ??
				findPendingTool(
					'propose_file_edit'
				);


			if (
				pendingTool
			) {

				pendingTool.status.className =
					'toolStatus waiting';


				pendingTool.status.textContent =
					'WAITING';
			}


			const card =
				document.createElement(
					'div'
				);


			card.className =
				'approvalCard';


			const title =
				document.createElement(
					'div'
				);


			title.className =
				'approvalTitle';


			title.textContent =
				'Approval Required';


			const path =
				document.createElement(
					'div'
				);


			path.className =
				'approvalPath';


			path.textContent =
				typeof message.path === 'string'
					? message.path
					: '';


			const summary =
				document.createElement(
					'div'
				);


			summary.className =
				'approvalSummary';


			summary.textContent =
				typeof message.summary === 'string'
					? message.summary
					: 'Review this proposed change.';


			const status =
				document.createElement(
					'div'
				);


			status.className =
				'approvalStatus';


			status.textContent =
				'Waiting for your decision';


			const actions =
				document.createElement(
					'div'
				);


			actions.className =
				'approvalActions';


			const reviewButton =
				document.createElement(
					'button'
				);


			reviewButton.className =
				'secondary';


			reviewButton.textContent =
				'Review Diff';


			const applyButton =
				document.createElement(
					'button'
				);


			applyButton.className =
				'approvalApply';


			applyButton.textContent =
				'Apply Change';


			const rejectButton =
				document.createElement(
					'button'
				);


			rejectButton.className =
				'approvalReject';


			rejectButton.textContent =
				'Reject';


			const disableDecisionButtons =
				() => {

					applyButton.disabled =
						true;


					rejectButton.disabled =
						true;
				};


			reviewButton.addEventListener(
				'click',

				() => {

					vscode.postMessage({
						type:
							'reviewApprovalDiff',

						approvalId
					});
				}
			);


			applyButton.addEventListener(
				'click',

				() => {

					disableDecisionButtons();


					status.textContent =
						'Applying approved change...';


					vscode.postMessage({
						type:
							'approvalDecision',

						approvalId,

						decision:
							'apply'
					});
				}
			);


			rejectButton.addEventListener(
				'click',

				() => {

					disableDecisionButtons();


					status.textContent =
						'Rejecting change...';


					vscode.postMessage({
						type:
							'approvalDecision',

						approvalId,

						decision:
							'reject'
					});
				}
			);


			actions.appendChild(
				reviewButton
			);


			actions.appendChild(
				applyButton
			);


			actions.appendChild(
				rejectButton
			);


			card.appendChild(
				title
			);


			card.appendChild(
				path
			);


			card.appendChild(
				summary
			);


			card.appendChild(
				status
			);


			card.appendChild(
				actions
			);


			if (
				pendingTool
			) {

				pendingTool.card.appendChild(
					card
				);

			} else {

				currentActivityBlock.appendChild(
					card
				);
			}


			approvalCards.set(
				approvalId,
				{
					card,
					status,
					reviewButton,
					applyButton,
					rejectButton
				}
			);


			scrollBottom();
		}


		function resolveApprovalCard(
			message
		) {

			const approvalId =
				String(
					message.approvalId ||
					''
				);


			const entry =
				approvalCards.get(
					approvalId
				);


			if (!entry) {
				return;
			}


			entry.applyButton.disabled =
				true;


			entry.rejectButton.disabled =
				true;


			/*
			 * terminal approval action hardening
			 *
			 * The extension host already ignores stale decisions.
			 * The UI must also stop presenting terminal mutation
			 * controls as actionable.
			 */
			entry.reviewButton.disabled =
				true;


			entry.applyButton.style.display =
				'none';


			entry.rejectButton.style.display =
				'none';


			if (
				message.decision === 'apply'
			) {

				entry.status.textContent =
					'Approved';

			} else {

				entry.status.textContent =
					'Rejected';
			}
		}


		function cancelApprovalCard(
			message
		) {

			const approvalId =
				String(
					message.approvalId ||
					''
				);


			const entry =
				approvalCards.get(
					approvalId
				);


			if (!entry) {
				return;
			}


			entry.reviewButton.disabled =
				true;


			entry.applyButton.disabled =
				true;


			entry.rejectButton.disabled =
				true;


			/*
			 * terminal approval action hardening
			 *
			 * The extension host already ignores stale decisions.
			 * The UI must also stop presenting terminal mutation
			 * controls as actionable.
			 */
			entry.reviewButton.disabled =
				true;


			entry.applyButton.style.display =
				'none';


			entry.rejectButton.style.display =
				'none';


			entry.status.textContent =
				'Cancelled';
		}


		function markToolNotApplied(
			toolName,
			message
		) {

			for (
				let index =
					pendingToolCards.length - 1;

				index >= 0;

				index--
			) {

				const pending =
					pendingToolCards[index];


				if (
					pending.toolName === toolName
				) {

					pending.status.className =
						'toolStatus notApplied';


					pending.status.textContent =
						'NOT APPLIED';


					if (message) {

						const detail =
							document.createElement(
								'div'
							);


						detail.className =
							'toolArguments';


						detail.textContent =
							message;


						pending.card.appendChild(
							detail
						);
					}


					pendingToolCards.splice(
						index,
						1
					);


					scrollBottom();


					return true;
				}
			}


			return false;
		}


		/*
		 * ====================================================
		 * AGENT STATE
		 * ====================================================
		 */

		function setModelStatus(
			message
		) {

			if (
				modelName
			) {

				modelName.textContent =
					typeof message.model ===
						'string'
						? message.model
						: 'Not configured';
			}


			if (
				!modelConnection
			) {

				return;
			}


			modelConnection.className =
				'modelConnection';


			if (
				message.connected ===
					true
			) {

				modelConnection.classList.add(
					'connected'
				);

				modelConnection.textContent =
					'● Connected';

			} else if (
				message.connected ===
					false
			) {

				modelConnection.classList.add(
					'disconnected'
				);

				modelConnection.textContent =
					'● Disconnected';

			} else {

				modelConnection.classList.add(
					'checking'
				);

				modelConnection.textContent =
					'● Checking';
			}
		}


		function setState(
			state
		) {

			statusDot.className =
				'statusDot';


			switch (
				state
			) {

				case 'RUNNING':

					statusText.textContent =
						'Running';


					statusDot.classList.add(
						'running'
					);

					break;


				case 'COMPLETED':

					statusText.textContent =
						'Completed';


					statusDot.classList.add(
						'completed'
					);

					break;


				case 'STOPPED':

					statusText.textContent =
						'Stopped';


					statusDot.classList.add(
						'stopped'
					);

					break;


				case 'FAILED':

					statusText.textContent =
						'Failed';


					statusDot.classList.add(
						'failed'
					);

					break;


				default:

					statusText.textContent =
						'Idle';

					break;
			}
		}


		function setBusy(
			busy
		) {

			sendButton.disabled =
				busy;


			promptInput.disabled =
				busy;


			stopButton.disabled =
				!busy;


			if (!busy) {

				stopButton.textContent =
					'Stop';
			}
		}


		/*
		 * ====================================================
		 * SUBMIT
		 * ====================================================
		 */

		if (
			configureModelButton
		) {

			configureModelButton.addEventListener(
				'click',

				() => {

					vscode.postMessage({
						type:
							'configureModel'
					});
				}
			);
		}


		function submit() {

			const task =
				String(
					promptInput?.value ??
					''
				)
					.trim();


			if (!task) {
				return;
			}


			vscode.postMessage({
				type:
					'submitTask',

				task
			});


			promptInput.value =
				'';
		}


		/*
		 * ====================================================
		 * SEND BUTTON
		 * ====================================================
		 */

		sendButton.addEventListener(
			'click',

			submit
		);


		stopButton.addEventListener(
			'click',

			() => {

				stopButton.disabled =
					true;


				stopButton.textContent =
					'Stopping...';


				vscode.postMessage({
					type:
						'stopAgent'
				});
			}
		);


		newConversationButton.addEventListener(
			'click',

			() => {

				vscode.postMessage({
					type:
						'newConversation'
				});
			}
		);


		/*
		 * ====================================================
		 * CMD/CTRL + ENTER
		 * ====================================================
		 */

		promptInput.addEventListener(
			'keydown',

			(event) => {

				if (
					event.key === 'Enter' &&
					(
						event.metaKey ||
						event.ctrlKey
					)
				) {

					event.preventDefault();


					submit();
				}
			}
		);


		/*
		 * ====================================================
		 * EXTENSION HOST -> WEBVIEW
		 * ====================================================
		 */

		window.addEventListener(
			'message',

			(event) => {

				const message =
					event.data;


				switch (
					message.type
				) {

					case 'user':

						addMessage(
							'You',

							message.text,

							'userMessage'
						);

						break;


					case 'assistant':

						addHtmlMessage(
							'Coding Agent',

							message.html,

							'assistantMessage'
						);

						break;


					case 'activity':

						addActivity(
							message.text
						);

						break;


					case 'error':

						addMessage(
							'Error',

							message.text,

							'errorMessage'
						);

						break;


					case 'state':

						setState(
							message.state
						);

						break;


					case 'workspace':

						workspace.textContent =
							message.text;


						workspace.title =
							message.text;

						break;


					case 'modelStatus':

						setModelStatus(
							message
						);

						break;


					case 'setBusy':

						setBusy(
							Boolean(
								message.value
							)
						);

						break;


					case 'approvalRequest':

						addApprovalRequest(
							message
						);

						break;


					case 'approvalResolved':

						resolveApprovalCard(
							message
						);

						break;


					case 'approvalCancelled':

						cancelApprovalCard(
							message
						);

						break;


					case 'clearConversation':

						clearConversation();

						break;
				}
			}
		);


		/*
		 * ====================================================
		 * INITIAL STATE
		 * ====================================================
		 */

		setState(
			'IDLE'
		);


		setBusy(
			false
		);


		vscode.postMessage({
			type:
				'webviewReady'
		});


		})();

	</script>

</body>

</html>
		`;
	}
}