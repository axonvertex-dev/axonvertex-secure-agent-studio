import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs/promises';
import { execFile } from 'child_process';


export interface GitDiffArgs {
	path?: string;
}


export interface GitDiffResult {
	diff: string;
	changed: boolean;
	path?: string;

	trackedDiffChanged: boolean;
	untrackedFiles: string[];

	/*
	 * true means the returned diff covers the requested scope without
	 * silent omission under this tool's configured limits.
	 */
	complete: boolean;
}


interface ExecResult {
	stdout: string;
	stderr: string;
	exitCode: number;
}


const COMMAND_TIMEOUT_MS =
	30_000;


const MAX_BUFFER_BYTES =
	4 * 1024 * 1024;


const MAX_DIFF_CHARS =
	3 * 1024 * 1024;


const MAX_UNTRACKED_FILES =
	100;


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


async function runGit(
	cwd: string,
	args: string[],
	allowedExitCodes: number[] = [0]
): Promise<ExecResult> {
	return await new Promise<
		ExecResult
	>(
		(
			resolve,
			reject
		) => {
			execFile(
				'git',
				args,
				{
					cwd,
					timeout:
						COMMAND_TIMEOUT_MS,
					maxBuffer:
						MAX_BUFFER_BYTES,
					encoding:
						'utf8'
				},
				(
					error,
					stdout,
					stderr
				) => {
					const rawExitCode =
						error
							? (
								error as {
									code?: unknown;
								}
							).code
							: undefined;


					const exitCode =
						typeof rawExitCode ===
							'number'
							? rawExitCode
							: (
								typeof rawExitCode ===
									'string' &&
								/^\d+$/.test(
									rawExitCode
								)
							)
								? Number(
									rawExitCode
								)
								: error
									? 1
									: 0;

					if (
						error &&
						!allowedExitCodes.includes(
							exitCode
						)
					) {
						reject(
							new Error(
								(
									stderr ||
									error.message
								).trim()
							)
						);

						return;
					}

					resolve({
						stdout:
							String(
								stdout ?? ''
							),

						stderr:
							String(
								stderr ?? ''
							),

						exitCode
					});
				}
			);
		}
	);
}


function validateRequestedPath(
	cwd: string,
	requested?: string
): {
	relativePath?: string;
	absolutePath?: string;
} {
	const raw =
		requested?.trim();

	if (
		!raw
	) {
		return {};
	}

	if (
		path.isAbsolute(
			raw
		)
	) {
		throw new Error(
			`git_diff path must be workspace-relative: ${raw}`
		);
	}

	if (
		/[\0\r\n]/.test(
			raw
		)
	) {
		throw new Error(
			'git_diff path contains prohibited control characters.'
		);
	}

	const absolutePath =
		path.resolve(
			cwd,
			raw
		);

	if (
		absolutePath ===
			cwd ||
		!isInsideRoot(
			cwd,
			absolutePath
		)
	) {
		throw new Error(
			`git_diff path is outside the workspace or does not name a file: ${raw}`
		);
	}

	const relativePath =
		path.relative(
			cwd,
			absolutePath
		);

	return {
		relativePath,
		absolutePath
	};
}


async function verifyExistingPathBoundary(
	cwd: string,
	absolutePath?: string
): Promise<void> {
	if (
		!absolutePath
	) {
		return;
	}

	try {
		const realRoot =
			await fs.realpath(
				cwd
			);

		const realTarget =
			await fs.realpath(
				absolutePath
			);

		if (
			!isInsideRoot(
				realRoot,
				realTarget
			)
		) {
			throw new Error(
				'git_diff target resolves outside the workspace through a symbolic link.'
			);
		}

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
			/*
			 * A tracked deletion may legitimately have no current
			 * filesystem object. Git still owns the path semantics.
			 */
			return;
		}

		throw error;
	}
}


async function listUntrackedFiles(
	cwd: string,
	relativePath?: string
): Promise<string[]> {
	const args = [
		'ls-files',
		'--others',
		'--exclude-standard',
		'-z'
	];

	if (
		relativePath
	) {
		args.push(
			'--',
			relativePath
		);
	}

	const result =
		await runGit(
			cwd,
			args
		);

	if (
		result.stderr.trim()
	) {
		throw new Error(
			result.stderr.trim()
		);
	}

	const files =
		result.stdout
			.split(
				'\0'
			)
			.filter(
				Boolean
			);

	if (
		files.length >
			MAX_UNTRACKED_FILES
	) {
		throw new Error(
			`git_diff found ${files.length} untracked files in scope; maximum supported is ${MAX_UNTRACKED_FILES}. Refusing to return an incomplete diff.`
		);
	}

	return files;
}


async function syntheticNewFileDiff(
	cwd: string,
	relativePath: string
): Promise<string> {
	const absolutePath =
		path.resolve(
			cwd,
			relativePath
		);

	if (
		!isInsideRoot(
			cwd,
			absolutePath
		)
	) {
		throw new Error(
			`Untracked path escaped workspace: ${relativePath}`
		);
	}

	await verifyExistingPathBoundary(
		cwd,
		absolutePath
	);

	/*
	 * git diff --no-index returns:
	 *   0 -> no difference
	 *   1 -> differences found
	 *
	 * Exit code 1 is therefore a successful diff result here.
	 */
	const result =
		await runGit(
			cwd,
			[
				'diff',
				'--no-index',
				'--no-ext-diff',
				'--',
				'/dev/null',
				relativePath
			],
			[
				0,
				1
			]
		);

	if (
		result.stderr.trim()
	) {
		throw new Error(
			result.stderr.trim()
		);
	}

	return result.stdout.trim();
}


function joinDiffs(
	parts: string[]
): string {
	const diff =
		parts
			.map(
				part =>
					part.trim()
			)
			.filter(
				Boolean
			)
			.join(
				'\n\n'
			);

	if (
		diff.length >
			MAX_DIFF_CHARS
	) {
		throw new Error(
			`git_diff output is too large (${diff.length} characters). Refusing to truncate security-relevant diff evidence.`
		);
	}

	return diff;
}


export async function gitDiffTool(
	args: GitDiffArgs
): Promise<GitDiffResult> {
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

	const cwd =
		path.resolve(
			folders[0].uri.fsPath
		);

	const {
		relativePath,
		absolutePath
	} =
		validateRequestedPath(
			cwd,
			args.path
		);

	await verifyExistingPathBoundary(
		cwd,
		absolutePath
	);

	const trackedArgs = [
		'diff',
		'--no-ext-diff',
		'--'
	];

	if (
		relativePath
	) {
		trackedArgs.push(
			relativePath
		);
	}

	try {
		const tracked =
			await runGit(
				cwd,
				trackedArgs
			);

		if (
			tracked.stderr.trim()
		) {
			throw new Error(
				tracked.stderr.trim()
			);
		}

		const trackedDiff =
			tracked.stdout.trim();

		const untrackedFiles =
			await listUntrackedFiles(
				cwd,
				relativePath
			);

		const parts:
			string[] =
		[];

		if (
			trackedDiff
		) {
			parts.push(
				trackedDiff
			);
		}

		for (
			const untrackedFile
			of untrackedFiles
		) {
			const synthetic =
				await syntheticNewFileDiff(
					cwd,
					untrackedFile
				);

			if (
				synthetic
			) {
				parts.push(
					synthetic
				);
			}
		}

		const diff =
			joinDiffs(
				parts
			);

		return {
			diff,

			changed:
				diff.length > 0,

			path:
				args.path,

			trackedDiffChanged:
				trackedDiff.length > 0,

			untrackedFiles,

			complete:
				true
		};

	} catch (
		error
	) {
		const message =
			error instanceof Error
				? error.message
				: String(
					error
				);

		throw new Error(
			`git_diff failed: ${message}`
		);
	}
}
