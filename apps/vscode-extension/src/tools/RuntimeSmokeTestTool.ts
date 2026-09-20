import * as vscode from 'vscode';
import * as path from 'path';
import * as net from 'net';
import * as fs from 'fs/promises';

import {
	ChildProcess,
	spawn
} from 'child_process';


export type RuntimeSmokeHttpMethod =
	| 'GET'
	| 'POST';


export interface RuntimeSmokeTestCheck {
	method?: RuntimeSmokeHttpMethod;
	path: string;
	expectedStatus?: number;

	/*
	 * Exact whole-response equality.
	 * Additional response fields cause this assertion to fail.
	 */
	expectedJson?: unknown;

	/*
	 * Object-subset equality.
	 * Additional response fields are allowed.
	 */
	expectedJsonSubset?: unknown;

	/*
	 * Top-level JSON key existence only.
	 */
	requiredJsonKeys?: string[];

	/*
	 * POST JSON body. body is retained for compatibility.
	 */
	jsonBody?: unknown;
	body?: unknown;
}


export interface RuntimeSmokeTestArgs {
	app: string;
	checks: RuntimeSmokeTestCheck[];
	timeoutSeconds?: number;
}


export interface RuntimeSmokeTestCheckResult {
	method: RuntimeSmokeHttpMethod;
	path: string;
	status: number | null;
	passed: boolean;
	responseJson?: unknown;
	responseText?: string;
	failures: string[];
	error?: string;
}


export interface RuntimeSmokeTestResult {
	success: boolean;
	app: string;

	/*
	 * Exact Python executable selected for this runtime execution.
	 * This is execution evidence and should not be inferred.
	 */
	pythonExecutable: string;

	command: string[];
	checks: RuntimeSmokeTestCheckResult[];
	processTerminated: boolean;
	stdout: string;
	stderr: string;
	error?: string;
}


export interface RuntimeSmokeTestContext {
	signal?: AbortSignal;
}


const MAX_CHECKS = 20;
const MIN_TIMEOUT_SECONDS = 3;
const MAX_TIMEOUT_SECONDS = 60;
const DEFAULT_TIMEOUT_SECONDS = 20;
const MAX_PROCESS_OUTPUT_CHARS = 20_000;
const MAX_RESPONSE_TEXT_CHARS = 20_000;


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
	if (signal?.aborted) {
		throw createAbortError();
	}
}


function clipText(
	value: string,
	maxChars: number
): string {
	if (value.length <= maxChars) {
		return value;
	}

	return (
		value.slice(
			0,
			maxChars
		) +
		`\n...[truncated ${value.length - maxChars} chars]`
	);
}


function getWorkspaceRoot(): string {
	const folders =
		vscode.workspace.workspaceFolders;

	if (!folders || folders.length === 0) {
		throw new Error(
			'No VS Code workspace is currently open.'
		);
	}

	return path.resolve(
		folders[0].uri.fsPath
	);
}


async function fileExists(
	filePath: string
): Promise<boolean> {

	try {

		/*
		 * Node fs.stat follows symbolic links.
		 *
		 * This is important on macOS where:
		 *
		 *   .venv/bin/python -> python3.14
		 *
		 * must still be recognized as the workspace Python
		 * executable.
		 */
		const stat =
			await fs.stat(
				filePath
			);


		return stat.isFile();

	} catch {

		return false;
	}
}


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

	for (const candidate of candidates) {
		if (await fileExists(candidate)) {
			return candidate;
		}
	}

	if (process.env.PYTHON?.trim()) {
		return process.env.PYTHON.trim();
	}

	return process.platform === 'win32'
		? 'python'
		: 'python3';
}


/*
 * Exact deep equality for JSON-compatible values.
 */
function jsonDeepEqual(
	actual: unknown,
	expected: unknown
): boolean {
	if (Object.is(actual, expected)) {
		return true;
	}

	if (actual === null || expected === null) {
		return false;
	}

	if (
		Array.isArray(actual) ||
		Array.isArray(expected)
	) {
		if (
			!Array.isArray(actual) ||
			!Array.isArray(expected) ||
			actual.length !== expected.length
		) {
			return false;
		}

		return expected.every(
			(expectedItem, index) =>
				jsonDeepEqual(
					actual[index],
					expectedItem
				)
		);
	}

	if (
		typeof actual === 'object' &&
		typeof expected === 'object'
	) {
		const actualObject =
			actual as Record<string, unknown>;

		const expectedObject =
			expected as Record<string, unknown>;

		const actualKeys =
			Object.keys(actualObject);

		const expectedKeys =
			Object.keys(expectedObject);

		if (
			actualKeys.length !==
			expectedKeys.length
		) {
			return false;
		}

		return expectedKeys.every(
			key =>
				Object.prototype.hasOwnProperty.call(
					actualObject,
					key
				) &&
				jsonDeepEqual(
					actualObject[key],
					expectedObject[key]
				)
		);
	}

	return false;
}


/*
 * Object-subset equality.
 *
 * Arrays remain strict to avoid ambiguous "subset" semantics.
 */
function jsonSubsetMatches(
	actual: unknown,
	expectedSubset: unknown
): boolean {
	if (
		expectedSubset === null ||
		typeof expectedSubset !== 'object'
	) {
		return Object.is(
			actual,
			expectedSubset
		);
	}

	if (Array.isArray(expectedSubset)) {
		if (
			!Array.isArray(actual) ||
			actual.length !== expectedSubset.length
		) {
			return false;
		}

		return expectedSubset.every(
			(expectedItem, index) =>
				jsonSubsetMatches(
					actual[index],
					expectedItem
				)
		);
	}

	if (
		actual === null ||
		typeof actual !== 'object' ||
		Array.isArray(actual)
	) {
		return false;
	}

	const actualObject =
		actual as Record<string, unknown>;

	const expectedObject =
		expectedSubset as Record<string, unknown>;

	for (
		const [key, expectedValue]
		of Object.entries(expectedObject)
	) {
		if (
			!Object.prototype.hasOwnProperty.call(
				actualObject,
				key
			)
		) {
			return false;
		}

		if (
			!jsonSubsetMatches(
				actualObject[key],
				expectedValue
			)
		) {
			return false;
		}
	}

	return true;
}


function validateAppTarget(
	app: string
): string {
	const value =
		app?.trim();

	if (!value) {
		throw new Error(
			'runtime_smoke_test requires app, for example app:app.'
		);
	}

	if (
		!/^[_A-Za-z][_A-Za-z0-9]*(?:\.[_A-Za-z][_A-Za-z0-9]*)*:[_A-Za-z][_A-Za-z0-9]*$/
			.test(value)
	) {
		throw new Error(
			`Invalid FastAPI app target: ${app}`
		);
	}

	return value;
}


function validateChecks(
	checks: RuntimeSmokeTestCheck[]
): void {
	if (
		!Array.isArray(checks) ||
		checks.length === 0
	) {
		throw new Error(
			'runtime_smoke_test requires at least one HTTP check.'
		);
	}

	if (checks.length > MAX_CHECKS) {
		throw new Error(
			`Too many runtime checks: ${checks.length}. Maximum is ${MAX_CHECKS}.`
		);
	}

	for (const check of checks) {
		if (
			typeof check.path !== 'string' ||
			!check.path.startsWith('/')
		) {
			throw new Error(
				`Runtime check path must start with '/': ${String(check.path)}`
			);
		}

		const method =
			String(
				check.method ?? 'GET'
			)
				.trim()
				.toUpperCase();

		if (
			method !== 'GET' &&
			method !== 'POST'
		) {
			throw new Error(
				`Unsupported HTTP method: ${method}`
			);
		}

		if (
			check.expectedStatus !== undefined &&
			(
				!Number.isInteger(
					check.expectedStatus
				) ||
				check.expectedStatus < 100 ||
				check.expectedStatus > 599
			)
		) {
			throw new Error(
				`Invalid expectedStatus for ${check.path}: ${String(check.expectedStatus)}`
			);
		}

		if (
			check.requiredJsonKeys !== undefined &&
			(
				!Array.isArray(
					check.requiredJsonKeys
				) ||
				check.requiredJsonKeys.some(
					key =>
						typeof key !== 'string' ||
						!key.trim()
				)
			)
		) {
			throw new Error(
				`requiredJsonKeys must be a string array for ${check.path}.`
			);
		}
	}
}


async function reserveEphemeralPort():
	Promise<number> {
	return await new Promise<number>(
		(resolve, reject) => {
			const server =
				net.createServer();

			server.once(
				'error',
				reject
			);

			server.listen(
				0,
				'127.0.0.1',
				() => {
					const address =
						server.address();

					if (
						!address ||
						typeof address === 'string'
					) {
						server.close();

						reject(
							new Error(
								'Could not reserve an ephemeral localhost port.'
							)
						);

						return;
					}

					const port =
						address.port;

					server.close(
						error => {
							if (error) {
								reject(error);
								return;
							}

							resolve(port);
						}
					);
				}
			);
		}
	);
}


async function canConnect(
	port: number
): Promise<boolean> {
	return await new Promise<boolean>(
		resolve => {
			const socket =
				net.createConnection({
					host: '127.0.0.1',
					port
				});

			let settled =
				false;

			const finish = (
				value: boolean
			) => {
				if (settled) {
					return;
				}

				settled =
					true;

				socket.destroy();

				resolve(value);
			};

			socket.setTimeout(
				500
			);

			socket.once(
				'connect',
				() => finish(true)
			);

			socket.once(
				'error',
				() => finish(false)
			);

			socket.once(
				'timeout',
				() => finish(false)
			);
		}
	);
}


async function waitForServer(
	port: number,
	processHandle: ChildProcess,
	timeoutMs: number,
	signal?: AbortSignal
): Promise<void> {
	const startedAt =
		Date.now();

	while (
		Date.now() - startedAt <
			timeoutMs
	) {
		throwIfAborted(signal);

		if (
			processHandle.exitCode !== null
		) {
			throw new Error(
				`FastAPI process exited before becoming ready with code ${String(processHandle.exitCode)}.`
			);
		}

		if (await canConnect(port)) {
			return;
		}

		await new Promise<void>(
			resolve =>
				setTimeout(
					resolve,
					150
				)
		);
	}

	throw new Error(
		`FastAPI process did not become ready within ${Math.ceil(timeoutMs / 1000)} seconds.`
	);
}


async function terminateProcess(
	child: ChildProcess
): Promise<boolean> {
	if (
		child.exitCode !== null ||
		child.killed
	) {
		return true;
	}

	try {
		child.kill('SIGTERM');
	} catch {
		// Continue to bounded wait / force kill.
	}

	const terminatedGracefully =
		await new Promise<boolean>(
			resolve => {
				let settled =
					false;

				const finish = (
					value: boolean
				) => {
					if (settled) {
						return;
					}

					settled =
						true;

					clearTimeout(timer);
					resolve(value);
				};

				const timer =
					setTimeout(
						() => finish(false),
						1500
					);

				child.once(
					'exit',
					() => finish(true)
				);
			}
		);

	if (terminatedGracefully) {
		return true;
	}

	try {
		child.kill('SIGKILL');
	} catch {
		// Evaluate state below.
	}

	await new Promise<void>(
		resolve =>
			setTimeout(
				resolve,
				150
			)
	);

	return (
		child.exitCode !== null ||
		child.killed
	);
}


async function executeHttpCheck(
	port: number,
	check: RuntimeSmokeTestCheck,
	signal?: AbortSignal
): Promise<RuntimeSmokeTestCheckResult> {
	throwIfAborted(signal);

	const method =
		String(
			check.method ?? 'GET'
		)
			.trim()
			.toUpperCase() as
				RuntimeSmokeHttpMethod;

	const expectedStatus =
		check.expectedStatus ?? 200;

	const failures:
		string[] =
		[];

	const requestBody =
		check.jsonBody !== undefined
			? check.jsonBody
			: check.body;

	const controller =
		new AbortController();

	const timeout =
		setTimeout(
			() => controller.abort(),
			5000
		);

	const parentAbort = () =>
		controller.abort();

	signal?.addEventListener(
		'abort',
		parentAbort,
		{
			once: true
		}
	);

	try {
		const headers:
			Record<string, string> =
		{};

		let body:
			string | undefined;

		if (
			method === 'POST' &&
			requestBody !== undefined
		) {
			headers[
				'Content-Type'
			] =
				'application/json';

			body =
				JSON.stringify(
					requestBody
				);
		}

		const response =
			await fetch(
				`http://127.0.0.1:${port}${check.path}`,
				{
					method,
					headers,
					body,
					signal:
						controller.signal
				}
			);

		const responseText =
			await response.text();

		let responseJson:
			unknown =
			undefined;

		if (responseText.trim()) {
			try {
				responseJson =
					JSON.parse(
						responseText
					);
			} catch {
				// JSON-specific assertions fail below.
			}
		}

		if (
			response.status !==
			expectedStatus
		) {
			failures.push(
				`Expected HTTP ${expectedStatus}, got ${response.status}.`
			);
		}

		if (
			check.expectedJson !==
			undefined
		) {
			if (
				responseJson ===
				undefined
			) {
				failures.push(
					'Expected exact JSON response, but response was not valid JSON.'
				);
			} else if (
				!jsonDeepEqual(
					responseJson,
					check.expectedJson
				)
			) {
				failures.push(
					'JSON response did not exactly match expectedJson.'
				);
			}
		}

		if (
			check.expectedJsonSubset !==
			undefined
		) {
			if (
				responseJson ===
				undefined
			) {
				failures.push(
					'Expected JSON subset, but response was not valid JSON.'
				);
			} else if (
				!jsonSubsetMatches(
					responseJson,
					check.expectedJsonSubset
				)
			) {
				failures.push(
					'JSON response did not contain the expected JSON subset.'
				);
			}
		}

		if (
			check.requiredJsonKeys !==
			undefined
		) {
			if (
				responseJson === null ||
				typeof responseJson !==
					'object' ||
				Array.isArray(
					responseJson
				)
			) {
				failures.push(
					'requiredJsonKeys was specified, but response JSON was not an object.'
				);
			} else {
				const object =
					responseJson as
						Record<
							string,
							unknown
						>;

				for (
					const key
					of check.requiredJsonKeys
				) {
					if (
						!Object.prototype
							.hasOwnProperty.call(
								object,
								key
							)
					) {
						failures.push(
							`Required JSON key missing: ${key}`
						);
					}
				}
			}
		}

		return {
			method,
			path:
				check.path,
			status:
				response.status,
			passed:
				failures.length === 0,
			responseJson,
			responseText:
				clipText(
					responseText,
					MAX_RESPONSE_TEXT_CHARS
				),
			failures
		};
	} catch (error) {
		if (signal?.aborted) {
			throw createAbortError();
		}

		const message =
			error instanceof Error
				? error.message
				: String(error);

		return {
			method,
			path:
				check.path,
			status:
				null,
			passed:
				false,
			failures: [
				message
			],
			error:
				message
		};
	} finally {
		clearTimeout(timeout);

		signal?.removeEventListener(
			'abort',
			parentAbort
		);
	}
}


export async function runtimeSmokeTestTool(
	args: RuntimeSmokeTestArgs,
	contextOrSignal:
		| RuntimeSmokeTestContext
		| AbortSignal =
	{}
): Promise<RuntimeSmokeTestResult> {
	const candidate =
		contextOrSignal as
			AbortSignal;

	const signal =
		typeof candidate?.aborted ===
			'boolean' &&
		typeof candidate?.addEventListener ===
			'function'
			? candidate
			: (
				contextOrSignal as
					RuntimeSmokeTestContext
			).signal;

	throwIfAborted(signal);

	const workspaceRoot =
		getWorkspaceRoot();

	const app =
		validateAppTarget(
			args.app
		);

	validateChecks(
		args.checks
	);

	const timeoutSeconds =
		Math.min(
			MAX_TIMEOUT_SECONDS,
			Math.max(
				MIN_TIMEOUT_SECONDS,
				Number.isFinite(
					args.timeoutSeconds
				)
					? Number(
						args.timeoutSeconds
					)
					: DEFAULT_TIMEOUT_SECONDS
			)
		);

	const python =
		await resolvePythonExecutable(
			workspaceRoot
		);

	const port =
		await reserveEphemeralPort();

	const command =
	[
		python,
		'-m',
		'uvicorn',
		app,
		'--host',
		'127.0.0.1',
		'--port',
		String(port),
		'--log-level',
		'warning'
	];

	let stdout =
		'';

	let stderr =
		'';

	let child:
		ChildProcess |
		undefined;

	let processTerminated =
		false;

	const results:
		RuntimeSmokeTestCheckResult[] =
		[];

	let toolError:
		string |
		undefined;

	try {
		child =
			spawn(
				command[0],
				command.slice(1),
				{
					cwd:
						workspaceRoot,
					env: {
						...process.env,
						PYTHONDONTWRITEBYTECODE:
							'1'
					},
					stdio: [
						'ignore',
						'pipe',
						'pipe'
					],
					shell:
						false
				}
			);

		child.stdout?.on(
			'data',
			chunk => {
				stdout =
					clipText(
						stdout +
						String(chunk),
						MAX_PROCESS_OUTPUT_CHARS
					);
			}
		);

		child.stderr?.on(
			'data',
			chunk => {
				stderr =
					clipText(
						stderr +
						String(chunk),
						MAX_PROCESS_OUTPUT_CHARS
					);
			}
		);

		const abortChild = () => {
			try {
				child?.kill(
					'SIGTERM'
				);
			} catch {
				// finally performs cleanup.
			}
		};

		signal?.addEventListener(
			'abort',
			abortChild,
			{
				once: true
			}
		);

		try {
			await waitForServer(
				port,
				child,
				Math.min(
					timeoutSeconds * 1000,
					15_000
				),
				signal
			);

			for (const check of args.checks) {
				throwIfAborted(signal);

				results.push(
					await executeHttpCheck(
						port,
						check,
						signal
					)
				);
			}
		} finally {
			signal?.removeEventListener(
				'abort',
				abortChild
			);
		}
	} catch (error) {
		if (
			signal?.aborted ||
			(
				error instanceof Error &&
				error.name ===
					'AbortError'
			)
		) {
			throw createAbortError();
		}

		toolError =
			error instanceof Error
				? error.message
				: String(error);
	} finally {
		if (child) {
			processTerminated =
				await terminateProcess(
					child
				);
		}
	}

	const success =
		!toolError &&
		results.length ===
			args.checks.length &&
		results.every(
			result =>
				result.passed
		) &&
		processTerminated;

	return {
		success,
		app,

		pythonExecutable:
			python,

		command,
		checks:
			results,
		processTerminated,
		stdout,
		stderr,
		...(toolError
			? {
				error:
					toolError
			}
			: {})
	};
}
