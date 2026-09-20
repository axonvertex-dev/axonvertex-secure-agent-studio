import {
	readFileTool,
	ReadFileArgs
} from './ReadFileTool';

import {
	listFilesTool,
	ListFilesArgs
} from './ListFilesTool';

import {
	searchCodeTool,
	SearchCodeArgs
} from './SearchCodeTool';

import {
	proposeFileEditTool,
	ProposeFileEditArgs,
	FileEditApprovalRequest,
	FileEditDecision
} from './ProposeFileEditTool';

import {
	createFileTool,
	CreateFileArgs
} from './CreateFileTool';

import {
	gitDiffTool,
	GitDiffArgs
} from './GitDiffTool';

import {
	runTestTool,
	RunTestArgs
} from './RunTestTool';

import {
	runtimeSmokeTestTool,
	RuntimeSmokeTestArgs
} from './RuntimeSmokeTestTool';


export interface ToolCall {

	id: string;

	type:
		'function';

	function: {

		name: string;

		arguments: string;
	};
}


export interface ToolExecutionContext {

	signal?: AbortSignal;

	requestFileEditApproval?: (
		request:
			FileEditApprovalRequest
	) => Promise<FileEditDecision>;
}


export const toolSchemas = [

	/*
	 * ========================================================
	 * READ FILE
	 * ========================================================
	 */

	{
		type:
			'function',

		function: {

			name:
				'read_file',

			description:
				'Read a UTF-8 text file from the active VS Code workspace. The path must be relative to the workspace root.',

			parameters: {

				type:
					'object',

				properties: {

					path: {

						type:
							'string',

						description:
							'Workspace-relative file path.'
					}
				},

				required:
				[
					'path'
				]
			}
		}
	},


	/*
	 * ========================================================
	 * LIST FILES
	 * ========================================================
	 */

	{
		type:
			'function',

		function: {

			name:
				'list_files',

			description:
				'Discover files in the active VS Code workspace using a glob pattern.',

			parameters: {

				type:
					'object',

				properties: {

					pattern: {

						type:
							'string',

						description:
							'Optional workspace glob pattern such as **/*.py.'
					}
				},

				required:
					[]
			}
		}
	},


	/*
	 * ========================================================
	 * SEARCH CODE
	 * ========================================================
	 */

	{
		type:
			'function',

		function: {

			name:
				'search_code',

			description:
				'Search literal text inside workspace files and return matching paths and locations.',

			parameters: {

				type:
					'object',

				properties: {

					query: {

						type:
							'string'
					},

					glob: {

						type:
							'string'
					},

					caseSensitive: {

						type:
							'boolean'
					},

					maxResults: {

						type:
							'number'
					}
				},

				required:
					[
						'query'
					]
			}
		}
	},


	/*
	 * ========================================================
	 * PROPOSE FILE EDIT
	 * ========================================================
	 */

	{
		type:
			'function',

		function: {

			name:
				'propose_file_edit',

			description:
				'Propose complete replacement content for an existing workspace file. The current file must be read first. Agent Studio requires explicit human approval before applying the edit.',

			parameters: {

				type:
					'object',

				properties: {

					path: {

						type:
							'string'
					},

					newContent: {

						type:
							'string'
					},

					summary: {

						type:
							'string'
					}
				},

				required:
					[
						'path',
						'newContent',
						'summary'
					]
			}
		}
	},

	/*
	 * ========================================================
	 * CREATE FILE
	 * ========================================================
	 *
	 * New-file-only mutation. Explicit human approval is
	 * required before any workspace file or directory is made.
	 */
	{
		type: 'function',
		function: {
			name: 'create_file',
			description:
				'Propose creation of a new workspace file. The target must not already exist. Agent Studio shows a diff from an empty file and requires explicit human approval before creating it. Never use this tool to overwrite an existing file.',
			parameters: {
				type: 'object',
				properties: {
					path: {
						type: 'string',
						description:
							'Workspace-relative path for the new file. Absolute paths and paths outside the workspace are rejected.'
					},
					content: {
						type: 'string',
						description:
							'Complete contents of the new file.'
					},
					summary: {
						type: 'string',
						description:
							'Short explanation of why this new file is required.'
					}
				},
				required: [
					'path',
					'content',
					'summary'
				]
			}
		}
	},


	/*
	 * ========================================================
	 * RUN TEST / VERIFICATION
	 * ========================================================
	 */

	{
		type:
			'function',

		function: {

			name:
				'run_test',

			description:
				'Run a controlled repository verification. python_compile checks syntax only. python_import verifies that a Python dependency can be imported. python_import_file imports and executes the top-level code of a workspace Python module. pytest and npm_test execute repository-controlled test code.',

			parameters: {

				type:
					'object',

				properties: {

					type: {

						type:
							'string',

						enum:
							[
								'python_compile',
								'python_import',
								'python_import_file',
								'pytest',
								'npm_test'
							]
					},

					path: {

						type:
							'string',

						description:
							'Workspace-relative path when required by the selected verification type.'
					},

					module: {

						type:
							'string',

						description:
							'Python module name for python_import, for example cryptography or fastapi.'
					}
				},

				required:
					[
						'type'
					]
			}
		}
	},


	/*
	 * ========================================================
	 * FASTAPI RUNTIME SMOKE TEST
	 * ========================================================
	 */

	{
			type:
				'function',

			function: {
				name:
					'runtime_smoke_test',

				description:
					'Start a FastAPI/uvicorn application on localhost and perform controlled GET/POST HTTP verification. Missing method defaults to GET. Use expectedJson for exact whole-response equality, expectedJsonSubset when additional response fields are allowed, and requiredJsonKeys for key existence only.',

				parameters: {
					type:
						'object',

					properties: {
						app: {
							type:
								'string',

							description:
								'Uvicorn module target such as app:app.'
						},

						checks: {
							type:
								'array',

							minItems:
								1,

							maxItems:
								20,

							items: {
								type:
									'object',

								properties: {
									method: {
										type:
											'string',

										enum: [
											'GET',
											'POST'
										],

										default:
											'GET',

										description:
											'HTTP method. Defaults to GET when omitted.'
									},

									path: {
										type:
											'string',

										description:
											'HTTP path beginning with /.'
									},

									expectedStatus: {
										type:
											'number',

										description:
											'Expected HTTP status. Defaults to 200.'
									},

									expectedJson: {
										type:
											'object',

										description:
											'Exact whole-response JSON equality. Additional response fields cause failure.'
									},

									expectedJsonSubset: {
										type:
											'object',

										description:
											'Required JSON fields and values. Additional response fields are allowed.'
									},

									requiredJsonKeys: {
										type:
											'array',

										items: {
											type:
												'string'
										},

										description:
											'Top-level JSON keys that must exist. Values are not checked.'
									},

									jsonBody: {
										type:
											'object',

										description:
											'Optional JSON request body for POST.'
									}
								},

								required: [
									'path'
								]
							}
						},

						timeoutSeconds: {
							type:
								'number',

							minimum:
								3,

							maximum:
								60
						}
					},

					required: [
						'app',
						'checks'
					]
				}
			}
		},


	/*
	 * ========================================================
	 * GIT DIFF
	 * ========================================================
	 */

	{
		type:
			'function',

		function: {

			name:
				'git_diff',

			description:
				'Read the current Git diff for the active repository or a specific workspace-relative file.',

			parameters: {

				type:
					'object',

				properties: {

					path: {

						type:
							'string'
					}
				},

				required:
					[]
			}
		}
	}
];


export async function executeTool(
	toolCall: ToolCall,
	context: ToolExecutionContext = {}
): Promise<unknown> {

	const name =
		toolCall.function.name;


	let args:
		unknown;


	try {

		args =
			JSON.parse(
				toolCall.function.arguments
			);

	} catch {

		throw new Error(
			`Invalid tool arguments for ${name}: ${toolCall.function.arguments}`
		);
	}


	switch (
		name
	) {

		case 'read_file':

			return await readFileTool(
				args as ReadFileArgs
			);


		case 'list_files':

			return await listFilesTool(
				args as ListFilesArgs
			);


		case 'search_code':

			return await searchCodeTool(
				args as SearchCodeArgs
			);


		case 'create_file':
			return await createFileTool(
				args as CreateFileArgs,
				{
					signal:
						context.signal,

					requestApproval:
						context.requestFileEditApproval
				}
			);

		case 'propose_file_edit':

			return await proposeFileEditTool(
				args as ProposeFileEditArgs,
				{
					signal:
						context.signal,

					requestApproval:
						context.requestFileEditApproval
				}
			);


		case 'run_test':

			return await runTestTool(
				args as RunTestArgs,
				{
					signal:
						context.signal
				}
			);


		case 'runtime_smoke_test':

			return await runtimeSmokeTestTool(
				args as RuntimeSmokeTestArgs,
				{
					signal:
						context.signal
				}
			);


		case 'git_diff':

			return await gitDiffTool(
				args as GitDiffArgs
			);


		default:

			throw new Error(
				`Unknown tool requested by Coding Agent: ${name}`
			);
	}
}
