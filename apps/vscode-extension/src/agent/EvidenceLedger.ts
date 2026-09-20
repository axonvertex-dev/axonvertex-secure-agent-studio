import type {
	ToolCall
} from '../tools/ToolRegistry';


export interface RuntimeEvidence {

	method: string;

	path: string;

	status:
		number | null;

	passed: boolean;
}


export interface EvidenceSnapshot {

	discoveredFiles: string[];

	readFiles: string[];

	proposedFiles: string[];

	approvedFiles: string[];

	modifiedFiles: string[];

	rejectedFiles: string[];

	syntaxVerified: string[];

	dependenciesVerified: string[];

	importsVerified: string[];

	testsPassed: string[];

	testsFailed: string[];

	runtimeChecksPassed:
		RuntimeEvidence[];

	runtimeChecksFailed:
		RuntimeEvidence[];

	runtimeProcessCleanupVerified:
		boolean;

	diffVerified: string[];

	toolExecutionCounts:
		Record<string, number>;


	toolErrors:
		string[];
}


function parseArguments(
	toolCall: ToolCall
): Record<string, unknown> {

	try {

		const parsed =
			JSON.parse(
				toolCall.function.arguments
			);


		if (
			parsed &&
			typeof parsed ===
				'object' &&
			!Array.isArray(
				parsed
			)
		) {

			return parsed as
				Record<string, unknown>;
		}

	} catch {

		/*
		 * ToolRegistry will report malformed arguments.
		 */
	}


	return {};
}


function getString(
	value: unknown
): string | undefined {

	return typeof value ===
		'string' &&
		value.trim()
		? value.trim()
		: undefined;
}


function collectPaths(
	value: unknown,
	output: Set<string>
): void {

	if (
		typeof value ===
			'string'
	) {

		/*
		 * Only treat strings resembling repository paths
		 * as discovered paths.
		 */

		if (
			value.includes(
				'/'
			) ||
			value.includes(
				'.'
			)
		) {

			output.add(
				value
			);
		}


		return;
	}


	if (
		Array.isArray(
			value
		)
	) {

		for (
			const item
			of value
		) {

			collectPaths(
				item,
				output
			);
		}


		return;
	}


	if (
		!value ||
		typeof value !==
			'object'
	) {

		return;
	}


	const record =
		value as
			Record<string, unknown>;


	const directPath =
		getString(
			record.path
		) ??
		getString(
			record.file
		) ??
		getString(
			record.filePath
		);


	if (
		directPath
	) {

		output.add(
			directPath
		);
	}


	for (
		const key
		of [
			'files',
			'matches',
			'results'
		]
	) {

		if (
			record[key] !==
				undefined
		) {

			collectPaths(
				record[key],
				output
			);
		}
	}
}


export class EvidenceLedger {

	private readonly discoveredFiles =
		new Set<string>();


	private readonly readFiles =
		new Set<string>();


	private readonly proposedFiles =
		new Set<string>();


	private readonly approvedFiles =
		new Set<string>();


	private readonly modifiedFiles =
		new Set<string>();


	private readonly rejectedFiles =
		new Set<string>();


	private readonly syntaxVerified =
		new Set<string>();


	private readonly dependenciesVerified =
		new Set<string>();


	private readonly importsVerified =
		new Set<string>();


	private readonly testsPassed =
		new Set<string>();


	private readonly testsFailed =
		new Set<string>();


	private readonly runtimeChecksPassed:
		RuntimeEvidence[] =
		[];


	private readonly runtimeChecksFailed:
		RuntimeEvidence[] =
		[];


	private runtimeProcessCleanupVerified =
		false;


	private readonly diffVerified =
		new Set<string>();


	private readonly toolExecutionCounts =
		new Map<string, number>();


	private readonly toolErrors:
		string[] =
		[];


	/*
	 * ========================================================
	 * TOOL EXECUTION EVIDENCE
	 * ========================================================
	 */

	private recordToolExecution(
		toolName: string
	): void {

		const current =
			this.toolExecutionCounts
				.get(
					toolName
				) ??
			0;


		this.toolExecutionCounts.set(
			toolName,
			current + 1
		);
	}


	/*
	 * ========================================================
	 * RECORD SUCCESSFUL TOOL RESULT
	 * ========================================================
	 */

	public recordToolResult(
		toolCall: ToolCall,
		result: unknown
	): void {


		this.recordToolExecution(
			toolCall.function.name
		);


		const name =
			toolCall.function.name;


		const args =
			parseArguments(
				toolCall
			);


		switch (
			name
		) {


			case 'list_files':
			case 'search_code': {

				collectPaths(
					result,
					this.discoveredFiles
				);


				break;
			}


			case 'read_file': {

				const file =
					getString(
						args.path
					);


				if (
					file
				) {

					this.discoveredFiles.add(
						file
					);


					this.readFiles.add(
						file
					);
				}


				break;
			}


			case 'create_file':
			case 'propose_file_edit': {

				const file =
					getString(
						args.path
					);


				if (
					!file
				) {

					break;
				}


				this.proposedFiles.add(
					file
				);


				const record =
					result &&
					typeof result ===
						'object'
						? result as
							Record<string, unknown>
						: {};


				if (
					record.applied ===
						true
				) {

					this.approvedFiles.add(
						file
					);


					this.modifiedFiles.add(
						file
					);

				} else if (
					record.applied ===
						false
				) {

					this.rejectedFiles.add(
						file
					);
				}


				break;
			}


			case 'run_test': {

				this.recordRunTest(
					args,
					result
				);


				break;
			}


			case 'runtime_smoke_test': {

				this.recordRuntimeSmokeTest(
					result
				);


				break;
			}


			case 'git_diff': {

				const file =
					getString(
						args.path
					) ??
					'(repository)';


				const candidate =
					result &&
					typeof result ===
						'object'
						? result as {
							changed?: unknown;
							complete?: unknown;
							diff?: unknown;
						}
						: undefined;


				/*
				 * toolExecutionCounts records that git_diff ran.
				 *
				 * diffVerified is deliberately stronger: it means a
				 * complete, non-empty diff was actually observed.
				 */
				if (
					candidate?.changed ===
						true &&
					candidate.complete !==
						false &&
					typeof candidate.diff ===
						'string' &&
					candidate.diff.trim().length >
						0
				) {

					this.diffVerified.add(
						file
					);
				}


				break;
			}
		}
	}


	/*
	 * ========================================================
	 * RECORD TOOL EXCEPTION
	 * ========================================================
	 */

	public recordToolError(
		toolCall: ToolCall,
		message: string
	): void {


		this.recordToolExecution(
			toolCall.function.name
		);


		const args =
			parseArguments(
				toolCall
			);


		this.toolErrors.push(
			`${toolCall.function.name}: ${message}`
		);


		if (
			toolCall.function.name ===
				'run_test'
		) {

			const type =
				getString(
					args.type
				) ??
				'unknown';


			const target =
				getString(
					args.path
				) ??
				getString(
					args.module
				) ??
				'workspace';


			this.testsFailed.add(
				`${type}:${target}`
			);
		}
	}


	/*
	 * ========================================================
	 * RUN TEST EVIDENCE
	 * ========================================================
	 */

	private recordRunTest(
		args:
			Record<string, unknown>,
		result:
			unknown
	): void {

		const type =
			getString(
				args.type
			);


		if (
			!type
		) {

			return;
		}


		const success =
			Boolean(
				result &&
				typeof result ===
					'object' &&
				(
					result as
						Record<
							string,
							unknown
						>
				).success ===
					true
			);


		const path =
			getString(
				args.path
			);


		const module =
			getString(
				args.module
			);


		const target =
			path ??
			module ??
			'workspace';


		if (
			success
		) {

			this.testsPassed.add(
				`${type}:${target}`
			);

		} else {

			this.testsFailed.add(
				`${type}:${target}`
			);
		}


		switch (
			type
		) {

			case 'python_compile':

				if (
					success &&
					path
				) {

					this.syntaxVerified.add(
						path
					);
				}


				break;


			case 'python_import':

				if (
					success &&
					module
				) {

					this.dependenciesVerified.add(
						module
					);
				}


				break;


			case 'python_import_file':

				if (
					success &&
					path
				) {

					this.importsVerified.add(
						path
					);
				}


				break;
		}
	}


	/*
	 * ========================================================
	 * RUNTIME EVIDENCE
	 * ========================================================
	 */

	private recordRuntimeSmokeTest(
		result: unknown
	): void {

		if (
			!result ||
			typeof result !==
				'object'
		) {

			return;
		}


		const record =
			result as
				Record<string, unknown>;


		if (
			record.processTerminated ===
				true
		) {

			this.runtimeProcessCleanupVerified =
				true;
		}


		if (
			!Array.isArray(
				record.checks
			)
		) {

			return;
		}


		for (
			const rawCheck
			of record.checks
		) {

			if (
				!rawCheck ||
				typeof rawCheck !==
					'object'
			) {

				continue;
			}


			const check =
				rawCheck as
					Record<
						string,
						unknown
					>;


			const evidence:
				RuntimeEvidence =
			{
				method:
					getString(
						check.method
					) ??
					'UNKNOWN',

				path:
					getString(
						check.path
					) ??
					'/',

				status:
					typeof check.status ===
						'number'
						? check.status
						: null,

				passed:
					check.passed ===
						true
			};


			if (
				evidence.passed
			) {

				this.runtimeChecksPassed.push(
					evidence
				);

			} else {

				this.runtimeChecksFailed.push(
					evidence
				);
			}
		}
	}


	/*
	 * ========================================================
	 * SNAPSHOT
	 * ========================================================
	 */

	public snapshot():
		EvidenceSnapshot {

		const toolExecutionCounts:
			Record<string, number> =
		{};


		for (
			const [
				toolName,
				count
			]
			of this.toolExecutionCounts
				.entries()
		) {

			toolExecutionCounts[
				toolName
			] =
				count;
		}


		return {

			discoveredFiles:
				Array.from(
					this.discoveredFiles
				).sort(),

			readFiles:
				Array.from(
					this.readFiles
				).sort(),

			proposedFiles:
				Array.from(
					this.proposedFiles
				).sort(),

			approvedFiles:
				Array.from(
					this.approvedFiles
				).sort(),

			modifiedFiles:
				Array.from(
					this.modifiedFiles
				).sort(),

			rejectedFiles:
				Array.from(
					this.rejectedFiles
				).sort(),

			syntaxVerified:
				Array.from(
					this.syntaxVerified
				).sort(),

			dependenciesVerified:
				Array.from(
					this.dependenciesVerified
				).sort(),

			importsVerified:
				Array.from(
					this.importsVerified
				).sort(),

			testsPassed:
				Array.from(
					this.testsPassed
				).sort(),

			testsFailed:
				Array.from(
					this.testsFailed
				).sort(),

			runtimeChecksPassed:
				[
					...this.runtimeChecksPassed
				],

			runtimeChecksFailed:
				[
					...this.runtimeChecksFailed
				],

			runtimeProcessCleanupVerified:
				this.runtimeProcessCleanupVerified,

			diffVerified:
				Array.from(
					this.diffVerified
				).sort(),

			toolExecutionCounts,

			toolErrors:
				[
					...this.toolErrors
				]
		};
	}


	/*
	 * ========================================================
	 * MODEL CONTEXT
	 * ========================================================
	 */

	public toModelContext(): string {

		const evidence =
			this.snapshot();


		const modelEvidence =
		{
			toolExecutionCounts:
				evidence.toolExecutionCounts,

			discoveredFiles: {
				count:
					evidence.discoveredFiles.length,

				sample:
					evidence.discoveredFiles.slice(
						0,
						50
					)
			},

			readFiles:
				evidence.readFiles.slice(
					-100
				),

			proposedFiles:
				evidence.proposedFiles,

			approvedFiles:
				evidence.approvedFiles,

			modifiedFiles:
				evidence.modifiedFiles,

			rejectedFiles:
				evidence.rejectedFiles,

			syntaxVerified:
				evidence.syntaxVerified,

			dependenciesVerified:
				evidence.dependenciesVerified,

			importsVerified:
				evidence.importsVerified,

			testsPassed:
				evidence.testsPassed.slice(
					-100
				),

			testsFailed:
				evidence.testsFailed.slice(
					-100
				),

			runtimeChecksPassed:
				evidence.runtimeChecksPassed.slice(
					-50
				),

			runtimeChecksFailed:
				evidence.runtimeChecksFailed.slice(
					-50
				),

			runtimeProcessCleanupVerified:
				evidence.runtimeProcessCleanupVerified,

			diffVerified:
				evidence.diffVerified,

			toolErrors:
				evidence.toolErrors.slice(
					-25
				)
		};


		return `
MACHINE-TRACKED AGENT STUDIO EVIDENCE

The following evidence was generated deterministically from actual
tool executions in this agent run.

Treat this machine-tracked evidence as authoritative when describing
what was inspected, changed, tested, or runtime verified.

Do not claim a stronger evidence level than appears here.

Important distinctions:

- discoveredFiles means a path was discovered, not necessarily read.
- readFiles means read_file successfully executed for that file.
- proposedFiles means a file mutation was proposed (edit or creation).
- approvedFiles means a file mutation received approval and was applied.
- syntaxVerified means python_compile succeeded.
- dependenciesVerified means python_import succeeded.
- importsVerified means python_import_file succeeded.
- runtimeChecksPassed contains only HTTP checks that actually passed.
- runtimeProcessCleanupVerified confirms runtime cleanup.
- diffVerified means git_diff returned a complete, non-empty diff for that scope. git_diff execution itself is recorded by toolExecutionCounts.
- testsFailed and toolErrors must not be described as successes.
- Anything not represented by evidence should be described as
  inferred or not verified.

- toolExecutionCounts records tools that ACTUALLY executed during
  this run. list_files, read_file, search_code, git_diff and similar
  operations are real tool executions even when they are not runtime
  application tests.

- An empty runtimeChecksPassed set means application runtime behavior
  has not been runtime verified by runtime_smoke_test.

- Reading source code for a runtime or approval tool verifies static
  architecture only. It does not prove that workflow was exercised.


Evidence:

${JSON.stringify(
	modelEvidence,
	null,
	2
)}
		`.trim();
	}
}
