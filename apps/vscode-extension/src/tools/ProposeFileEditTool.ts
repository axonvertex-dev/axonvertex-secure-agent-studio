import * as vscode from 'vscode';
import * as path from 'path';


export interface ProposeFileEditArgs {
	path: string;
	newContent: string;
	summary: string;
}


export interface ProposeFileEditResult {
	path: string;
	applied: boolean;
	message: string;
}


export type FileEditDecision =
	| 'apply'
	| 'reject';


export interface FileEditApprovalRequest {
	path: string;
	summary: string;
	originalUri: vscode.Uri;
	proposedUri: vscode.Uri;
}


export interface ProposeFileEditContext {
	signal?: AbortSignal;
	requestApproval?: (
		request: FileEditApprovalRequest
	) => Promise<FileEditDecision>;
}


const MAX_FILE_BYTES =
	512 * 1024;


function createAbortError(): Error {
	const error =
		new Error(
			'Agent stopped by user.'
		);

	error.name =
		'AbortError';

	return error;
}


function throwIfAborted(
	signal?: AbortSignal
): void {
	if (
		signal?.aborted
	) {
		throw createAbortError();
	}
}


async function requestNativeApproval(
	args: ProposeFileEditArgs
): Promise<FileEditDecision> {
	const decision =
		await vscode.window.showWarningMessage(
			[
				'Agent Studio Coding Agent proposes a file change.',
				'',
				`File: ${args.path}`,
				`Summary: ${args.summary || 'No summary provided.'}`,
				'',
				'Review the diff before approving.'
			].join('\n'),
			{
				modal: true
			},
			'Apply Change',
			'Reject'
		);

	return decision ===
		'Apply Change'
		? 'apply'
		: 'reject';
}


export async function proposeFileEditTool(
	args: ProposeFileEditArgs,
	context: ProposeFileEditContext = {}
): Promise<ProposeFileEditResult> {
	throwIfAborted(
		context.signal
	);

	const folders =
		vscode.workspace.workspaceFolders;

	if (
		!folders ||
		folders.length === 0
	) {
		throw new Error(
			'No VS Code workspace is currently open.'
		);
	}

	if (
		!args.path?.trim()
	) {
		throw new Error(
			'propose_file_edit requires a file path.'
		);
	}

	if (
		typeof args.newContent !==
		'string'
	) {
		throw new Error(
			'propose_file_edit requires newContent.'
		);
	}

	const workspaceRoot =
		folders[0].uri;

	const rootPath =
		path.resolve(
			workspaceRoot.fsPath
		);

	const requestedPath =
		path.resolve(
			rootPath,
			args.path
		);

	if (
		requestedPath !== rootPath &&
		!requestedPath.startsWith(
			rootPath + path.sep
		)
	) {
		throw new Error(
			`Path is outside workspace: ${args.path}`
		);
	}

	const uri =
		vscode.Uri.file(
			requestedPath
		);

	let stat:
		vscode.FileStat;

	try {
		stat =
			await vscode.workspace.fs.stat(
				uri
			);
	} catch {
		throw new Error(
			`File does not exist: ${args.path}`
		);
	}

	if (
		stat.type !==
		vscode.FileType.File
	) {
		throw new Error(
			`Not a file: ${args.path}`
		);
	}

	if (
		stat.size >
		MAX_FILE_BYTES
	) {
		throw new Error(
			`File too large to edit: ${args.path}`
		);
	}

	throwIfAborted(
		context.signal
	);

	const document =
		await vscode.workspace.openTextDocument(
			uri
		);

	const oldContent =
		document.getText();

	if (
		oldContent ===
		args.newContent
	) {
		return {
			path:
				args.path,

			applied:
				false,

			message:
				'Proposed content is identical to the current file.'
		};
	}

	throwIfAborted(
		context.signal
	);

	/*
	 * Create a temporary in-memory document containing the
	 * complete proposed replacement.
	 */
	const proposedDocument =
		await vscode.workspace.openTextDocument({
			language:
				document.languageId,

			content:
				args.newContent
		});

	/*
	 * Open the native VS Code diff immediately.
	 */
	/*
	 * Open the diff asynchronously.
	 *
	 * IMPORTANT:
	 * Do not await vscode.diff here. Human approval is owned
	 * by the Agent Studio sidebar and must be requested
	 * immediately after the preview is launched.
	 */
	void vscode.commands.executeCommand(
		'vscode.diff',
		document.uri,
		proposedDocument.uri,
		`Agent Studio Proposal: ${args.path}`,
		{
			preview:
				true
		}
	);

	throwIfAborted(
		context.signal
	);

	const approvalRequest:
		FileEditApprovalRequest =
	{
		path:
			args.path,

		summary:
			args.summary ||
			'No summary provided.',

		originalUri:
			document.uri,

		proposedUri:
			proposedDocument.uri
	};

	/*
	 * Preferred path: the Agent Studio sidebar owns the
	 * human approval gate.
	 *
	 * Fallback path: command-palette callers retain a native
	 * modal approval dialog.
	 */
	console.log(
		'[AgentStudio][Approval] ProposeFileEditTool requesting approval',
		{
			path: args.path,
			hasRequestApproval:
				Boolean(
					context.requestApproval
				)
		}
	);

	const decision =
		context.requestApproval
			? await context.requestApproval(
				approvalRequest
			)
			: await requestNativeApproval(
				args
			);

	console.log(
		'[AgentStudio][Approval] decision received',
		{
			path: args.path,
			decision
		}
	);

	throwIfAborted(
		context.signal
	);

	if (
		decision !==
		'apply'
	) {
		return {
			path:
				args.path,

			applied:
				false,

			message:
				'User rejected the proposed change.'
		};
	}

	/*
	 * Apply only after explicit human approval.
	 */
	const edit =
		new vscode.WorkspaceEdit();

	const fullRange =
		new vscode.Range(
			document.positionAt(
				0
			),
			document.positionAt(
				oldContent.length
			)
		);

	edit.replace(
		document.uri,
		fullRange,
		args.newContent
	);

	throwIfAborted(
		context.signal
	);

	const success =
		await vscode.workspace.applyEdit(
			edit
		);

	if (
		!success
	) {
		throw new Error(
			`VS Code failed to apply edit to ${args.path}`
		);
	}

	throwIfAborted(
		context.signal
	);

	const saved =
		await document.save();

	if (
		!saved
	) {
		throw new Error(
			`Edit applied but file could not be saved: ${args.path}`
		);
	}

	return {
		path:
			args.path,

		applied:
			true,

		message:
			'User approved the change and VS Code applied it successfully.'
	};
}
