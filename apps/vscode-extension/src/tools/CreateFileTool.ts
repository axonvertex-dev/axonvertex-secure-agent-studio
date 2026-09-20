import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs/promises';
import * as crypto from 'crypto';

import type {
	FileEditApprovalRequest,
	FileEditDecision
} from './ProposeFileEditTool';


export interface CreateFileArgs {
	path: string;
	content: string;
	summary: string;
}


export interface CreateFileResult {
	path: string;
	applied: boolean;
	created: boolean;
	contentVerified: boolean;
	contentBytes: number;
	sha256?: string;
	operation: 'create';
	message: string;
}


export interface CreateFileContext {
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


function isInsideRoot(
	root: string,
	candidate: string
): boolean {
	return (
		candidate === root ||
		candidate.startsWith(
			root + path.sep
		)
	);
}


async function pathExists(
	filePath: string
): Promise<boolean> {
	try {
		await fs.lstat(
			filePath
		);

		return true;

	} catch (
		error
	) {
		const code =
			(
				error as
					NodeJS.ErrnoException
			).code;

		if (
			code === 'ENOENT'
		) {
			return false;
		}

		throw error;
	}
}


/*
 * Resolve the nearest existing parent and ensure it remains within
 * the real workspace root.
 *
 * This rejects existing symlink-parent escapes such as:
 *
 *   workspace/outside -> /tmp
 *   create_file("outside/file.txt")
 */
async function verifyParentBoundary(
	rootPath: string,
	requestedPath: string
): Promise<void> {
	const realRoot =
		await fs.realpath(
			rootPath
		);

	let ancestor =
		path.dirname(
			requestedPath
		);

	while (
		!await pathExists(
			ancestor
		)
	) {
		const parent =
			path.dirname(
				ancestor
			);

		if (
			parent === ancestor
		) {
			throw new Error(
				'Could not resolve an existing parent directory for the requested file.'
			);
		}

		ancestor =
			parent;
	}

	const realAncestor =
		await fs.realpath(
			ancestor
		);

	if (
		!isInsideRoot(
			realRoot,
			realAncestor
		)
	) {
		throw new Error(
			'Requested file would escape the workspace through a symbolic-link parent.'
		);
	}
}


function guessLanguageId(
	filePath: string
): string {
	switch (
		path.extname(
			filePath
		)
			.toLowerCase()
	) {
		case '.ts':
			return 'typescript';

		case '.tsx':
			return 'typescriptreact';

		case '.js':
			return 'javascript';

		case '.jsx':
			return 'javascriptreact';

		case '.py':
			return 'python';

		case '.json':
			return 'json';

		case '.md':
			return 'markdown';

		case '.yaml':
		case '.yml':
			return 'yaml';

		case '.sh':
			return 'shellscript';

		case '.html':
			return 'html';

		case '.css':
			return 'css';

		default:
			return 'plaintext';
	}
}


function sha256(
	value: Buffer
): string {
	return crypto
		.createHash(
			'sha256'
		)
		.update(
			value
		)
		.digest(
			'hex'
		);
}


async function requestNativeApproval(
	args: CreateFileArgs
): Promise<FileEditDecision> {
	const decision =
		await vscode.window.showWarningMessage(
			[
				'Agent Studio Coding Agent proposes creating a new file.',
				'',
				`File: ${args.path}`,
				`Summary: ${args.summary || 'No summary provided.'}`,
				'',
				'Review the proposed file before approving.'
			].join(
				'\n'
			),
			{
				modal:
					true
			},
			'Create File',
			'Reject'
		);

	return decision ===
		'Create File'
		? 'apply'
		: 'reject';
}


export async function createFileTool(
	args: CreateFileArgs,
	context: CreateFileContext = {}
): Promise<CreateFileResult> {
	throwIfAborted(
		context.signal
	);

	const folders =
		vscode.workspace.workspaceFolders;

	if (
		!folders ||
		folders.length ===
			0
	) {
		throw new Error(
			'No VS Code workspace is currently open.'
		);
	}

	if (
		!args.path?.trim()
	) {
		throw new Error(
			'create_file requires a workspace-relative file path.'
		);
	}

	if (
		path.isAbsolute(
			args.path
		)
	) {
		throw new Error(
			`create_file requires a workspace-relative path: ${args.path}`
		);
	}

	if (
		/[\0\r\n]/.test(
			args.path
		)
	) {
		throw new Error(
			'create_file path contains prohibited control characters.'
		);
	}

	if (
		typeof args.content !==
			'string'
	) {
		throw new Error(
			'create_file requires content.'
		);
	}

	if (
		typeof args.summary !==
			'string' ||
		!args.summary.trim()
	) {
		throw new Error(
			'create_file requires a non-empty summary.'
		);
	}

	const proposedBytes =
		Buffer.from(
			args.content,
			'utf8'
		);

	if (
		proposedBytes.length >
			MAX_FILE_BYTES
	) {
		throw new Error(
			`Proposed file is too large: ${proposedBytes.length} bytes. Maximum is ${MAX_FILE_BYTES} bytes.`
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
		requestedPath ===
			rootPath ||
		!isInsideRoot(
			rootPath,
			requestedPath
		)
	) {
		throw new Error(
			`Path is outside workspace or does not name a file: ${args.path}`
		);
	}

	await verifyParentBoundary(
		rootPath,
		requestedPath
	);

	if (
		await pathExists(
			requestedPath
		)
	) {
		throw new Error(
			`File already exists. Use propose_file_edit instead: ${args.path}`
		);
	}

	throwIfAborted(
		context.signal
	);

	const languageId =
		guessLanguageId(
			args.path
		);

	/*
	 * Preview only. These documents are in-memory and do not mutate
	 * the workspace before approval.
	 */
	const emptyDocument =
		await vscode.workspace.openTextDocument({
			language:
				languageId,

			content:
				''
		});

	const proposedDocument =
		await vscode.workspace.openTextDocument({
			language:
				languageId,

			content:
				args.content
		});

	void vscode.commands.executeCommand(
		'vscode.diff',
		emptyDocument.uri,
		proposedDocument.uri,
		`Agent Studio New File Proposal: ${args.path}`,
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
			args.summary.trim(),

		originalUri:
			emptyDocument.uri,

		proposedUri:
			proposedDocument.uri
	};

	const decision =
		context.requestApproval
			? await context.requestApproval(
				approvalRequest
			)
			: await requestNativeApproval(
				args
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

			created:
				false,

			contentVerified:
				false,

			contentBytes:
				0,

			operation:
				'create',

			message:
				'User rejected the proposed file creation.'
		};
	}

	/*
	 * Re-check after human approval.
	 *
	 * The target must still be absent, and the nearest existing
	 * parent must still resolve inside the workspace.
	 */
	if (
		await pathExists(
			requestedPath
		)
	) {
		throw new Error(
			`File appeared before creation and will not be overwritten: ${args.path}`
		);
	}

	await verifyParentBoundary(
		rootPath,
		requestedPath
	);

	throwIfAborted(
		context.signal
	);

	/*
	 * Commit region:
	 *
	 * Once this begins, do not convert a successful filesystem
	 * mutation into an AbortError before recording its result.
	 *
	 * fs.writeFile(..., flag: 'wx') performs an exclusive create and
	 * therefore refuses to overwrite a file that appears in a race.
	 */
	await fs.mkdir(
		path.dirname(
			requestedPath
		),
		{
			recursive:
				true
		}
	);

	try {
		await fs.writeFile(
			requestedPath,
			proposedBytes,
			{
				flag:
					'wx'
			}
		);

	} catch (
		error
	) {
		const code =
			(
				error as
					NodeJS.ErrnoException
			).code;

		if (
			code === 'EEXIST'
		) {
			throw new Error(
				`File appeared before creation and will not be overwritten: ${args.path}`
			);
		}

		throw error;
	}

	const actualBytes =
		await fs.readFile(
			requestedPath
		);

	const contentVerified =
		actualBytes.equals(
			proposedBytes
		);

	if (
		!contentVerified
	) {
		/*
		 * Fail closed. A file whose bytes do not match the approved
		 * proposal must not remain as an apparently successful
		 * mutation.
		 */
		try {
			await fs.unlink(
				requestedPath
			);
		} catch {
			// Preserve the verification failure below.
		}

		throw new Error(
			`Created file content verification failed: ${args.path}`
		);
	}

	return {
		path:
			args.path,

		applied:
			true,

		created:
			true,

		contentVerified:
			true,

		contentBytes:
			actualBytes.length,

		sha256:
			sha256(
				actualBytes
			),

		operation:
			'create',

		message:
			'User approved the file creation; the file was created without overwrite and its bytes were verified against the approved content.'
	};
}
