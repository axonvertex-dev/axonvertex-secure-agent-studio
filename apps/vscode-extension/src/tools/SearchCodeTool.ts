import * as vscode from 'vscode';

export interface SearchCodeArgs {
	query: string;
	glob?: string;
	caseSensitive?: boolean;
	maxResults?: number;
}

export interface SearchCodeMatch {
	path: string;
	line: number;
	column: number;
	preview: string;
}

export interface SearchCodeResult {
	query: string;
	matches: SearchCodeMatch[];
	filesScanned: number;
	truncated: boolean;
}

const MAX_FILES = 500;
const MAX_FILE_BYTES = 512 * 1024;
const DEFAULT_MAX_RESULTS = 100;

const EXCLUDE_GLOB =
	'**/{node_modules,.git,out,dist,build,.next,.venv,venv,__pycache__,.vscode-test}/**';

export async function searchCodeTool(
	args: SearchCodeArgs
): Promise<SearchCodeResult> {

	if (!vscode.workspace.workspaceFolders?.length) {
		throw new Error(
			'No VS Code workspace is currently open.'
		);
	}

	const query = args.query?.trim();

	if (!query) {
		throw new Error(
			'search_code requires a non-empty query.'
		);
	}

	const includeGlob =
		args.glob?.trim() || '**/*';

	const caseSensitive =
		args.caseSensitive ?? false;

	const requestedMax =
		args.maxResults ?? DEFAULT_MAX_RESULTS;

	const maxResults =
		Math.max(
			1,
			Math.min(
				requestedMax,
				DEFAULT_MAX_RESULTS
			)
		);

	const uris =
		await vscode.workspace.findFiles(
			includeGlob,
			EXCLUDE_GLOB,
			MAX_FILES
		);

	const needle =
		caseSensitive
			? query
			: query.toLowerCase();

	const matches: SearchCodeMatch[] = [];

	let filesScanned = 0;
	let truncated = false;

	for (const uri of uris) {

		if (matches.length >= maxResults) {
			truncated = true;
			break;
		}

		try {

			const stat =
				await vscode.workspace.fs.stat(uri);

			if (
				stat.type !== vscode.FileType.File ||
				stat.size > MAX_FILE_BYTES
			) {
				continue;
			}

			const bytes =
				await vscode.workspace.fs.readFile(uri);

			const text =
				new TextDecoder().decode(bytes);

			/*
			 * Cheap binary-file protection.
			 */
			if (text.includes('\0')) {
				continue;
			}

			filesScanned++;

			const lines =
				text.split(/\r?\n/);

			for (
				let lineIndex = 0;
				lineIndex < lines.length;
				lineIndex++
			) {

				const line =
					lines[lineIndex];

				const haystack =
					caseSensitive
						? line
						: line.toLowerCase();

				let start = 0;

				while (true) {

					const column =
						haystack.indexOf(
							needle,
							start
						);

					if (column === -1) {
						break;
					}

					matches.push({
						path:
							vscode.workspace.asRelativePath(
								uri,
								false
							),

						line:
							lineIndex + 1,

						column:
							column + 1,

						preview:
							line.trim().slice(0, 300)
					});

					if (
						matches.length >=
						maxResults
					) {
						truncated = true;
						break;
					}

					start =
						column +
						Math.max(
							needle.length,
							1
						);
				}

				if (truncated) {
					break;
				}
			}

		} catch {
			/*
			 * Skip unreadable/non-text files.
			 */
			continue;
		}
	}

	return {
		query,
		matches,
		filesScanned,
		truncated
	};
}