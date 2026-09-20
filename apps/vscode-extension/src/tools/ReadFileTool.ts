import * as vscode from 'vscode';
import * as path from 'path';

export interface ReadFileArgs {
	path: string;
}

export interface ReadFileResult {
	path: string;
	content: string;
}

const MAX_FILE_BYTES = 256 * 1024;

export async function readFileTool(
	args: ReadFileArgs
): Promise<ReadFileResult> {

	const folders = vscode.workspace.workspaceFolders;

	if (!folders || folders.length === 0) {
		throw new Error(
			'No VS Code workspace is currently open.'
		);
	}

	const workspaceRoot = folders[0].uri;

	const rootPath =
		path.resolve(workspaceRoot.fsPath);

	const requestedPath =
		path.resolve(rootPath, args.path);

	/*
	 * Security boundary:
	 * the agent may only read files inside the workspace.
	 */
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
		vscode.Uri.file(requestedPath);

	const stat =
		await vscode.workspace.fs.stat(uri);

	if (
		stat.type !==
		vscode.FileType.File
	) {
		throw new Error(
			`Not a file: ${args.path}`
		);
	}

	if (stat.size > MAX_FILE_BYTES) {
		throw new Error(
			`File too large: ${args.path} (${stat.size} bytes)`
		);
	}

	const bytes =
		await vscode.workspace.fs.readFile(uri);

	const content =
		new TextDecoder().decode(bytes);

	return {
		path: args.path,
		content
	};
}