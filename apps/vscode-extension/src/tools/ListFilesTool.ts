import * as vscode from 'vscode';

const MAX_RESULTS = 500;

export interface ListFilesArgs {
	pattern?: string;
}

export interface ListFilesResult {
	files: string[];
	truncated: boolean;
}

export async function listFilesTool(
	args: ListFilesArgs
): Promise<ListFilesResult> {
	if (!vscode.workspace.workspaceFolders?.length) {
		throw new Error(
			'No VS Code workspace is currently open.'
		);
	}

	const pattern = args.pattern?.trim() || '**/*';
	const uris = await vscode.workspace.findFiles(
		new vscode.RelativePattern(
			vscode.workspace.workspaceFolders[0],
			pattern
		),
		'**/{node_modules,.git,.venv,venv,__pycache__,.pytest_cache,.mypy_cache,.ruff_cache,out,dist,build}/**',
		MAX_RESULTS + 1
	);

	const files = uris
		.slice(0, MAX_RESULTS)
		.map((uri) =>
			vscode.workspace.asRelativePath(uri, false)
		)
		.sort();

	return {
		files,
		truncated: uris.length > MAX_RESULTS
	};
}