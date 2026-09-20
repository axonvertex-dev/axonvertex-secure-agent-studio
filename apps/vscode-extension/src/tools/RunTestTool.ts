import * as vscode from 'vscode';

import * as path from 'path';

import {
	execFile
} from 'child_process';


export type RunTestType =
	| 'python_compile'
	| 'python_import'
	| 'python_import_file'
	| 'pytest'
	| 'npm_test';


export interface RunTestArgs {

	type:
		RunTestType;

	path?: string;

	module?: string;
}


export interface RunTestResult {

	type:
		RunTestType;

	success: boolean;

	command: string;

	target?: string;

	exitCode:
		number | null;

	stdout: string;

	stderr: string;

	error?: string;
}


interface ProcessResult {

	success: boolean;

	exitCode:
		number | null;

	stdout: string;

	stderr: string;
}


const PROCESS_TIMEOUT_MS =
	30_000;


const MAX_OUTPUT_BYTES =
	256 * 1024;


/*
 * ============================================================
 * ABORT SUPPORT
 * ============================================================
 */

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


/*
 * ============================================================
 * WORKSPACE
 * ============================================================
 */

function getWorkspaceRoot(): string {

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


	return path.resolve(
		folders[0].uri.fsPath
	);
}


function resolveWorkspacePath(
	relativePath: string
): string {

	if (
		!relativePath?.trim()
	) {

		throw new Error(
			'A workspace-relative path is required.'
		);
	}


	const root =
		getWorkspaceRoot();


	const resolved =
		path.resolve(
			root,
			relativePath
		);


	if (
		resolved !== root &&
		!resolved.startsWith(
			root + path.sep
		)
	) {

		throw new Error(
			`Path is outside workspace: ${relativePath}`
		);
	}


	return resolved;
}


async function ensureExistingFile(
	relativePath: string
): Promise<string> {

	const resolved =
		resolveWorkspacePath(
			relativePath
		);


	let stat:
		vscode.FileStat;


	try {

		stat =
			await vscode.workspace.fs.stat(
				vscode.Uri.file(
					resolved
				)
			);

	} catch {

		throw new Error(
			`File does not exist: ${relativePath}`
		);
	}


	if (
		stat.type !==
			vscode.FileType.File
	) {

		throw new Error(
			`Path is not a file: ${relativePath}`
		);
	}


	return resolved;
}


/*
 * ============================================================
 * CONTROLLED PROCESS EXECUTION
 * ============================================================
 *
 * No shell is used.
 *
 * Executables and arguments are selected by this tool,
 * not supplied as arbitrary commands by the model.
 */

function runProcess(
	executable: string,
	args: string[],
	cwd: string,
	signal?: AbortSignal
): Promise<ProcessResult> {

	throwIfAborted(
		signal
	);


	return new Promise<ProcessResult>(
		(
			resolve,
			reject
		) => {

			let settled =
				false;


			const child =
				execFile(
					executable,
					args,
					{
						cwd,

						timeout:
							PROCESS_TIMEOUT_MS,

						maxBuffer:
							MAX_OUTPUT_BYTES,

						encoding:
							'utf8'
					},

					(
						error,
						stdout,
						stderr
					) => {

						if (
							settled
						) {

							return;
						}


						settled =
							true;


						signal?.removeEventListener(
							'abort',
							onAbort
						);


						let exitCode:
							number | null =
							0;


						if (
							error
						) {

							const errorCode =
								(
									error as
										Error & {
											code?:
												number |
												string;
										}
								).code;


							exitCode =
								typeof errorCode ===
									'number'
									? errorCode
									: null;
						}


						resolve({
							success:
								!error,

							exitCode,

							stdout:
								stdout ?? '',

							stderr:
								stderr ?? ''
						});
					}
				);


			const onAbort =
				() => {

					if (
						settled
					) {

						return;
					}


					settled =
						true;


					child.kill(
						'SIGTERM'
					);


					reject(
						createAbortError()
					);
				};


			signal?.addEventListener(
				'abort',
				onAbort,
				{
					once:
						true
				}
			);
		}
	);
}


/*
 * ============================================================
 * PYTHON RUNTIME DISCOVERY
 * ============================================================
 */

async function resolvePythonExecutable(
	workspaceRoot: string
): Promise<string> {

	const candidates =
		process.platform === 'win32'
			? [
				path.join(
					workspaceRoot,
					'.venv',
					'Scripts',
					'python.exe'
				),

				path.join(
					workspaceRoot,
					'venv',
					'Scripts',
					'python.exe'
				)
			]
			: [
				path.join(
					workspaceRoot,
					'.venv',
					'bin',
					'python'
				),

				path.join(
					workspaceRoot,
					'venv',
					'bin',
					'python'
				)
			];


	for (
		const candidate
		of candidates
	) {

		try {

			const stat =
				await vscode.workspace.fs.stat(
					vscode.Uri.file(
						candidate
					)
				);


			if (
				(
					stat.type &
						vscode.FileType.File
				) !== 0 ||
				(
					stat.type &
						vscode.FileType.SymbolicLink
				) !== 0
			) {

				return candidate;
			}

		} catch {

			/*
			 * Candidate does not exist.
			 */
		}
	}


	if (
		process.env.PYTHON?.trim()
	) {

		return process.env.PYTHON.trim();
	}


	return process.platform === 'win32'
		? 'python'
		: 'python3';
}


/*
 * ============================================================
 * TOOL
 * ============================================================
 */

export async function runTestTool(
	args: RunTestArgs,
	context: {
		signal?: AbortSignal;
	} = {}
): Promise<RunTestResult> {

	throwIfAborted(
		context.signal
	);


	const root =
		getWorkspaceRoot();


	const python =
		await resolvePythonExecutable(
			root
		);


	let executable =
		python;


	let processArgs:
		string[];


	let target:
		string | undefined;


	switch (
		args.type
	) {


		/*
		 * ----------------------------------------------------
		 * PYTHON SYNTAX
		 * ----------------------------------------------------
		 */

		case 'python_compile': {

			if (
				!args.path
			) {

				throw new Error(
					'python_compile requires path.'
				);
			}


			const file =
				await ensureExistingFile(
					args.path
				);


			if (
				path.extname(
					file
				) !== '.py'
			) {

				throw new Error(
					'python_compile requires a .py file.'
				);
			}


			processArgs =
			[
				'-m',
				'py_compile',
				file
			];


			target =
				args.path;


			break;
		}


		/*
		 * ----------------------------------------------------
		 * PYTHON DEPENDENCY IMPORT
		 * ----------------------------------------------------
		 */

		case 'python_import': {

			const moduleName =
				args.module?.trim();


			if (
				!moduleName
			) {

				throw new Error(
					'python_import requires module.'
				);
			}


			if (
				!/^[A-Za-z_][A-Za-z0-9_.]*$/
					.test(
						moduleName
					)
			) {

				throw new Error(
					`Invalid Python module name: ${moduleName}`
				);
			}


			processArgs =
			[
				'-c',

				[
					'import importlib, sys',
					'importlib.import_module(sys.argv[1])'
				].join('\n'),

				moduleName
			];


			target =
				moduleName;


			break;
		}


		/*
		 * ----------------------------------------------------
		 * IMPORT ACTUAL REPOSITORY PYTHON FILE
		 * ----------------------------------------------------
		 *
		 * This executes top-level Python module code.
		 *
		 * No arbitrary command or shell input is accepted.
		 */

		case 'python_import_file': {

			if (
				!args.path
			) {

				throw new Error(
					'python_import_file requires path.'
				);
			}


			const file =
				await ensureExistingFile(
					args.path
				);


			if (
				path.extname(
					file
				) !== '.py'
			) {

				throw new Error(
					'python_import_file requires a .py file.'
				);
			}


			processArgs =
			[
				'-c',

				[
					'import importlib.util, sys',
					'p = sys.argv[1]',
					'spec = importlib.util.spec_from_file_location("agent_studio_import_check", p)',
					'assert spec is not None and spec.loader is not None, f"Cannot import {p}"',
					'module = importlib.util.module_from_spec(spec)',
					'spec.loader.exec_module(module)'
				].join('\n'),

				file
			];


			target =
				args.path;


			break;
		}


		/*
		 * ----------------------------------------------------
		 * PYTEST
		 * ----------------------------------------------------
		 */

		case 'pytest': {

			processArgs =
			[
				'-m',
				'pytest'
			];


			if (
				args.path
			) {

				const resolved =
					resolveWorkspacePath(
						args.path
					);


				processArgs.push(
					resolved
				);


				target =
					args.path;
			}


			break;
		}


		/*
		 * ----------------------------------------------------
		 * NPM TEST
		 * ----------------------------------------------------
		 */

		case 'npm_test': {

			executable =
				process.platform ===
					'win32'
					? 'npm.cmd'
					: 'npm';


			processArgs =
			[
				'test'
			];


			target =
				'workspace';


			break;
		}


		default:

			throw new Error(
				`Unsupported test type: ${String(args.type)}`
			);
	}


	const result =
		await runProcess(
			executable,
			processArgs,
			root,
			context.signal
		);


	throwIfAborted(
		context.signal
	);


	const command =
		[
			executable,
			...processArgs
		].join(
			' '
		);


	return {
		type:
			args.type,

		success:
			result.success,

		command,

		target,

		exitCode:
			result.exitCode,

		stdout:
			result.stdout,

		stderr:
			result.stderr,

		error:
			result.success
				? undefined
				: (
					result.stderr.trim() ||
					`${args.type} failed.`
				)
	};
}
