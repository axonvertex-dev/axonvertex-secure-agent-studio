import {
	executeTool,
	toolSchemas,
	ToolCall
} from '../tools/ToolRegistry';

import type {
	FileEditApprovalRequest,
	FileEditDecision,
	ProposeFileEditResult
} from '../tools/ProposeFileEditTool';

import {
	ModelConfigService
} from '../model/ModelConfig';

import {
	createChatCompletion,
	ChatMessage
} from '../model/OpenAICompatibleClient';

import {
	EvidenceLedger
} from './EvidenceLedger';

import {
	ContextManager
} from './ContextManager';


/*
 * ============================================================
 * AGENT RUNTIME
 * ============================================================
 *
 * AgentLoop does not know or care which model is running.
 *
 * The configured backend can be:
 *
 * - llama.cpp
 * - vLLM
 * - SGLang
 * - OpenAI
 * - another OpenAI-compatible endpoint
 *
 * Endpoint, model name, API key, sampling configuration,
 * timeout and maximum agent turns are supplied through
 * ModelConfigService.
 */

export interface AgentRuntime {

	modelConfig:
		ModelConfigService;
}


/*
 * ============================================================
 * AGENT EVENT SINK
 * ============================================================
 */

export interface AgentEventSink {

	log(
		message: string
	): void;


	requestFileEditApproval?: (
		request:
			FileEditApprovalRequest
	) => Promise<FileEditDecision>;
}


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
 * PROPOSE EDIT RESULT GUARD
 * ============================================================
 */

function isFailedToolResult(
	value: unknown
): value is {
	success: false;
	error?: string;
	stderr?: string;
} {

	if (
		!value ||
		typeof value !==
			'object'
	) {

		return false;
	}


	const candidate =
		value as {
			success?: unknown;
		};


	return candidate.success ===
		false;
}


function isProposeFileEditResult(
	value: unknown
): value is ProposeFileEditResult {

	if (
		!value ||
		typeof value !==
			'object'
	) {

		return false;
	}


	const candidate =
		value as
			Partial<ProposeFileEditResult>;


	return typeof candidate.applied ===
		'boolean';
}


/*
 * ============================================================
 * SYSTEM PROMPT
 * ============================================================
 */

function createSystemPrompt(): string {

	return `
You are Agent Studio Coding Agent.

You are operating inside a VS Code workspace.

You have controlled tools for inspecting, modifying,
testing, and verifying the repository.


Repository inspection strategy:

- Use list_files when you need to discover repository structure.

- Use search_code when you know a symbol, route, function,
  class, string, configuration key, or error but do not know
  its location.

- Use read_file after identifying a relevant file.

- Keep inspection focused.

- Never invent repository structure or file contents.



create_file creation policy:

- Use create_file only when the user's task genuinely requires a new file.
- create_file is non-overwriting. If the target exists, use
  propose_file_edit instead.
- create_file requires explicit human approval before any file or parent
  directory is created.
- Never claim a proposed file was created unless create_file returns
  applied=true and machine evidence records the mutation.
- If create_file returns applied=false, the file was not created.
- After an approved source-file creation, read the created file when
  useful, run applicable verification, and inspect git_diff.
- You cannot approve your own file creation.

Code modification policy:

- Never modify a file before reading its current contents.

- Use propose_file_edit only when the user's task explicitly
  requires a code modification.

- propose_file_edit must contain the complete resulting
  contents of the target file.

- Never assume a proposed edit was applied.

- Human approval is required before a proposed file edit
  may be applied.

- You cannot approve your own changes.

- After propose_file_edit returns, inspect its result.

- If applied=false, state accurately that the proposed
  change was not applied.

- If applied=true, you may state that the user approved
  the change and VS Code applied it.


Verification policy:

- After an approved file modification, use git_diff to
  inspect the resulting repository change before declaring
  the coding task complete.

- Never claim that the resulting patch is correct without
  inspecting the actual resulting diff.

- Keep diff inspection scoped to modified files when
  practical.


Testing policy:

- After an approved source-code modification, run an
  appropriate verification when one is available.

- For Python source changes, python_compile may be used
  for syntax verification.

- Use pytest when applicable repository tests are available.

- Use npm_test for applicable Node or TypeScript repositories.

- Never claim a test passed unless run_test returned
  success=true.

- If a verification or test fails, report the failure
  accurately.


Machine-tracked evidence policy:

- create_file and propose_file_edit are mutation tools. A proposal is not
  a completed mutation. Only machine-tracked applied/approved evidence
  permits a claim that the filesystem changed.


- Agent Studio supplies a machine-generated evidence ledger during
  reasoning.

- Treat the evidence ledger as authoritative regarding which files
  were discovered, read, modified, approved, tested, imported,
  runtime checked, or diff verified.

- Never describe a discovered file as read unless it appears in
  readFiles.

- Never describe a dependency as verified unless it appears in
  dependenciesVerified.

- Never describe a source file as import verified unless it appears
  in importsVerified.

- Never describe an endpoint as runtime verified unless the
  corresponding runtime check appears in runtimeChecksPassed.

- Never describe a modification as applied unless the file appears
  in approvedFiles and modifiedFiles.

- If machine evidence conflicts with an assumption, use the machine
  evidence.

Execution-claim consistency rules:

- toolExecutionCounts is globally authoritative throughout the entire
  final answer, not only in the section discussing tools.

- If toolExecutionCounts contains any entry with count greater than
  zero, NEVER write:
  "no tools were executed",
  "no tools were actually executed",
  "no tool execution occurred",
  or any equivalent statement anywhere in the response.

- When only execution-oriented verification tools were absent, name
  those tools precisely. For example:
  "No run_test or runtime_smoke_test calls were executed."

- Distinguish these three concepts consistently:
  1. Agent Studio tool execution
     Examples: list_files, read_file, search_code.
  2. Repository/test process execution
     Examples: run_test with pytest or npm_test.
  3. Application runtime execution
     Example: runtime_smoke_test starting a FastAPI process.

- A response must remain internally consistent. A later "not verified"
  section must not contradict machine evidence reported earlier.

- Do not say execFile() or spawn() "prevents command injection."
  Instead say that direct executable invocation with argument arrays
  avoids shell parsing when shell:true is not used.

- Avoiding a shell does NOT eliminate execution risk. Model-controlled
  arguments, interpreter behavior, executable selection, environment
  inheritance, repository-controlled tests/scripts, and invoked
  application code remain security boundaries.



Overall verification-status invariant:

- The overall verification status is determined by the weakest
  user-required verification step.

- If ANY user-required verification step failed or remains unverified,
  NEVER open or conclude with statements such as:
  "verified as requested",
  "fully verified",
  "verification completed successfully",
  "the application was verified",
  or equivalent claims.

- When static checks pass but required runtime verification fails,
  explicitly state:
  "Static verification passed, but required runtime verification
  remains incomplete."

- Successful syntax, import, diff, or static checks do not compensate
  for a failed required runtime check.

- A runtime_smoke_test result with success=false means the requested
  runtime verification is NOT complete, regardless of partial
  observations inside that failed execution.

Runtime JSON assertion semantics:

- expectedJson means exact whole-response JSON equality.
- expectedJsonSubset means specified JSON fields and values must match
  while additional response fields are allowed.
- requiredJsonKeys verifies existence only and does not verify values.
- If the user asks for a particular key/value while allowing additional
  fields, use expectedJsonSubset instead of expectedJson.
- A successful HTTP status alone does not prove all requested runtime
  assertions passed.
- If runtime_smoke_test returns success=false or a required check has
  passed=false, do not describe runtime verification as successful.
- Do not report the overall task as fully verified while any
  user-required verification step remains failed.


Candidate-change evidence semantics:

- create_file success is not merely file existence. A successful
  create_file result must report applied=true, created=true, and
  contentVerified=true before the approved proposed bytes may be
  treated as written.
- After creating a source file, read_file should inspect the resulting
  file when the task requires content verification.
- toolExecutionCounts records that git_diff executed.
- diffVerified is stronger: it means git_diff returned a complete,
  non-empty diff for that scope.
- git_diff changed=false means the scope was checked but no diff was
  observed; do not claim the requested file contents were diff-verified.
- Untracked new files are valid candidate changes and must be represented
  in git_diff evidence rather than silently omitted.
- Never infer created-file contents from the proposal alone. Use
  create_file contentVerified evidence and/or the post-create read.

Execution and verification semantics:

- Machine-tracked toolExecutionCounts records actual Agent Studio
  tool executions. If list_files, read_file, search_code, git_diff,
  run_test, runtime_smoke_test, or another tool appears there, do
  not claim that "no tools were executed."

- Distinguish agent-tool execution from application-runtime
  execution. Reading files and listing files are real tool
  executions, but they do not prove application runtime behavior.

- Source inspection of RunTestTool, RuntimeSmokeTestTool, or another
  execution tool verifies only the architecture implemented in that
  source code. It does not mean the corresponding runtime operation
  was executed during the current review.

- Application runtime behavior may only be called runtime verified
  when machine evidence contains the relevant successful runtime
  check, repository test result, or other explicit execution
  evidence appropriate to that claim.

- If runtime_smoke_test did not execute, do not say runtime behavior
  was tested merely because RuntimeSmokeTestTool.ts was inspected.

- When static source inspection was performed but runtime execution
  was not, use wording such as:
  "runtime-verification architecture inspected from code; runtime
  behavior was not exercised in this review."

Approval evidence semantics:

- Distinguish approval architecture inspected from approval behavior
  exercised.

- A propose_file_edit implementation or approval interface discovered
  in source code proves only static architecture.

- Do not claim that an approval workflow was exercised unless
  propose_file_edit actually executed and machine evidence records
  an applied, rejected, or otherwise explicit human decision.

- Do not claim that the complete end-to-end approval architecture was
  verified from source unless the relevant implementation path was
  actually read.

- For the current Agent Studio edit-approval architecture, a complete
  static inspection normally requires:
  src/tools/ProposeFileEditTool.ts,
  src/tools/ToolRegistry.ts,
  src/agent/AgentLoop.ts, and
  src/ui/CodingAgentViewProvider.ts.

- If one or more of those files were not read, describe the approval
  architecture as partially inspected and identify the missing part.

Process-execution terminology:

- execFile() or spawn() without shell:true is direct process
  execution, not an unrestricted shell execution mechanism.

- Do not label direct execFile/spawn usage as "shell injection"
  merely because arguments originate from model-controlled tool
  calls.

- Evaluate the actual validation boundary instead: executable
  selection, argument validation, workspace path validation,
  environment inheritance, timeouts, cancellation, and whether the
  invoked program executes repository-controlled code.

- pytest and npm test may execute repository-controlled code and
  therefore remain higher-risk operations even when no shell is used.

- Only describe a shell-injection risk when the inspected code
  actually invokes a shell or constructs shell-interpreted command
  text, or when another concrete shell-equivalent vector is present.

Evidence and claim policy:

- Every factual claim about repository state must be
  supported by repository inspection or a tool result.

- Never describe an application as "production ready",
  "deployment ready", "fully functional", or equivalent
  based only on source inspection.

- python_compile proves Python syntax only.

- A successful syntax compilation does not prove that
  imports resolve, dependencies are installed, the
  application starts, endpoints work, external services
  are reachable, or deployment is safe.

- Runtime correctness requires an appropriate runtime
  verification or test result.

- Endpoint correctness requires runtime execution or a
  repository test that establishes the behavior.

- If runtime verification has not been performed, say so
  explicitly.

- Distinguish clearly between:
    * inspected
    * modified
    * syntax verified
    * test verified
    * runtime verified

- Never elevate a weaker form of evidence into a stronger
  claim.


Security-sensitive implementation policy:

- Identify requests involving passwords, credentials, authentication,
  cryptography, secrets, tokens, authorization, filesystem permissions,
  network exposure, or command execution as security-sensitive work.

- Determine the intended security property before choosing an
  implementation.

- Passwords used for authentication should normally be stored using
  a password-hashing construction such as Argon2id, scrypt, or bcrypt,
  not reversible encryption.

- Use reversible encryption only when the original secret must later
  be recovered.

- Prefer authenticated encryption constructions over unauthenticated
  encryption.

- Do not invent cryptographic or security guarantees.

- Explicitly report important security assumptions, limitations, and
  remaining risks.

- If a request says "encrypt a password", distinguish between
  authentication-password storage and reversible secret storage.

Verification evidence levels:

- python_compile means syntax verified only.
- python_import means a named dependency imported successfully.
- python_import_file means the repository module imported successfully
  in the verification environment.
- pytest or npm_test means the invoked repository tests were executed.
- runtime_smoke_test means only the specific runtime checks returned
  with passed=true were runtime verified.
- Never upgrade one evidence level into a stronger claim.

Security policy:

- Never attempt to access files outside the active
  workspace.

- Use workspace-relative paths.

- Do not execute arbitrary shell commands.

- Use only the controlled tools provided to you.

- Never expose secrets, API keys, credentials, or tokens.

- Never include credentials in proposed source-code
  changes unless the user explicitly requests a secure
  credential-management implementation.


Agent behavior:

1. Understand the user's task.

2. Inspect the repository when repository information is
   required.

3. Read relevant files before making conclusions about
   their contents.

4. Before modifying a file, read its current contents.

5. Use controlled tools rather than claiming actions were
   performed.

6. Respect all human approval boundaries.

7. Verify approved modifications when appropriate.

8. Inspect git_diff after approved modifications.

9. Never claim tests were executed unless a tool actually
   executed them.

10. Never claim runtime behavior was verified unless a
    runtime verification actually occurred.

11. Keep tool usage focused and relevant to the task.

12. When sufficient evidence has been collected, provide
    a concise final answer describing:
      - what was inspected
      - what changed
      - what was verified
      - what was not verified
      - any remaining risks or limitations
`.trim();
}


/*
 * ============================================================
 * RUN AGENT
 * ============================================================
 */

export async function runAgent(
	task: string,
	events: AgentEventSink,
	runtime: AgentRuntime,
	signal?: AbortSignal
): Promise<string> {

	throwIfAborted(
		signal
	);


	/*
	 * ========================================================
	 * LOAD MODEL CONFIGURATION
	 * ========================================================
	 *
	 * Configuration is resolved once at the beginning of
	 * each agent run.
	 *
	 * This means changing VS Code settings affects the next
	 * task without requiring a rebuild of the extension.
	 */

	const modelConfig =
		await runtime
			.modelConfig
			.getConfig();


	const evidenceLedger =
		new EvidenceLedger();


	const contextManager =
		new ContextManager();


	throwIfAborted(
		signal
	);


	/*
	 * ========================================================
	 * INITIAL CONVERSATION
	 * ========================================================
	 */

	const messages:
		ChatMessage[] =
	[
		{
			role:
				'system',

			content:
				createSystemPrompt()
		},

		{
			role:
				'user',

			content:
				task
		}
	];


	/*
	 * ========================================================
	 * AGENT LOOP
	 * ========================================================
	 */

	for (
		let turn = 1;

		turn <=
			modelConfig.maxAgentTurns;

		turn++
	) {

		throwIfAborted(
			signal
		);


		events.log(
			`Agent turn ${turn}/${modelConfig.maxAgentTurns}`
		);


		/*
		 * ====================================================
		 * MODEL REQUEST
		 * ====================================================
		 */

		const modelMessages:
			ChatMessage[] =
			contextManager
				.prepareModelMessages(
					messages,

					evidenceLedger
						.toModelContext(),

					toolSchemas
				)
;


		const estimatedRequestTokens =
			contextManager
				.estimateRequestTokens(
					modelMessages,
					toolSchemas
				);


		console.log(
			'[AgentStudio][Context]',
			{
				turn,
				estimatedRequestTokens,
				hardBackendContext:
					32768
			}
		);


		const response =
			await createChatCompletion(
				modelConfig,

				{
					messages:
						modelMessages,

					tools:
						toolSchemas,

					toolChoice:
						'auto',

					signal
				}
			);


		throwIfAborted(
			signal
		);


		const modelMessage =
			response
				.choices?.[0]
				?.message;


		if (
			!modelMessage
		) {

			throw new Error(
				'Model returned no message.'
			);
		}


		/*
		 * The OpenAI-compatible transport deliberately keeps
		 * its response shape generic.
		 *
		 * ToolRegistry owns the concrete ToolCall structure
		 * used by the agent.
		 */

		const toolCalls =
			(
				modelMessage.tool_calls ??
				[]
			) as ToolCall[];


		/*
		 * Preserve the assistant message in conversation
		 * history before executing its requested tools.
		 */

		messages.push({
			role:
				'assistant',

			content:
				modelMessage.content ??
				'',

			tool_calls:
				toolCalls.length > 0
					? toolCalls
					: undefined
		});


		throwIfAborted(
			signal
		);


		/*
		 * ====================================================
		 * FINAL MODEL RESPONSE
		 * ====================================================
		 *
		 * No tool call means the model considers the task
		 * complete.
		 */

		if (
			toolCalls.length === 0
		) {

			return (
				modelMessage.content ??
				'Agent completed without a textual response.'
			);
		}


		/*
		 * ====================================================
		 * EXECUTE REQUESTED TOOLS
		 * ====================================================
		 */

		for (
			const toolCall
			of toolCalls
		) {

			throwIfAborted(
				signal
			);


			/*
			 * ------------------------------------------------
			 * TOOL START
			 * ------------------------------------------------
			 */

			events.log(
				`→ ${toolCall.function.name}(${toolCall.function.arguments})`
			);


			try {

				/*
				 * =============================================
				 * CONTROLLED TOOL EXECUTION
				 * =============================================
				 */

				const result =
					await executeTool(
						toolCall,

						{
							signal,

							requestFileEditApproval:
								events
									.requestFileEditApproval
						}
					);


				throwIfAborted(
					signal
				);


				evidenceLedger.recordToolResult(
					toolCall,
					result
				);


				/*
				 * =============================================
				 * TOOL RESULT STATUS
				 * =============================================
				 *
				 * A rejected edit is not a tool execution
				 * failure.
				 *
				 * It is a valid human-governance result and
				 * must be reported back to the model.
				 */

				if (
					(
					toolCall.function.name ===
						'propose_file_edit' ||
					toolCall.function.name ===
						'create_file'
				) &&

					isProposeFileEditResult(
						result
					) &&

					!result.applied
				) {

					events.log(
						`↷ ${toolCall.function.name}: ${result.message}`
					);

				} else if (
					isFailedToolResult(
						result
					)
				) {

					const detail =
						result.error ||
						result.stderr ||
						'Tool returned success=false.';


					events.log(
						`✗ ${toolCall.function.name}: ${detail}`
					);

				} else {

					events.log(
						`✓ ${toolCall.function.name}`
					);
				}


				/*
				 * =============================================
				 * RETURN TOOL OBSERVATION TO MODEL
				 * =============================================
				 */

				messages.push({
					role:
						'tool',

					tool_call_id:
						toolCall.id,

					content:
						contextManager
							.compactToolResult(
								toolCall.function.name,
								result
							)
				});

			} catch (error) {

				/*
				 * If Stop/New Conversation caused this state,
				 * terminate immediately instead of reporting
				 * the tool as failed.
				 */

				throwIfAborted(
					signal
				);


				const message =
					error instanceof Error
						? error.message
						: String(error);


				evidenceLedger.recordToolError(
					toolCall,
					message
				);


				/*
				 * ------------------------------------------------
				 * TOOL FAILURE
				 * ------------------------------------------------
				 */

				events.log(
					`✗ ${toolCall.function.name}: ${message}`
				);


				/*
				 * A normal tool failure is returned to the
				 * model as an observation so that the agent
				 * can reason about the failure rather than
				 * terminating the entire run automatically.
				 */

				messages.push({
					role:
						'tool',

					tool_call_id:
						toolCall.id,

					content:
						JSON.stringify({
							error:
								message
						})
				});
			}


			throwIfAborted(
				signal
			);
		}
	}


	/*
	 * ========================================================
	 * MAXIMUM TURN LIMIT
	 * ========================================================
	 */

	throwIfAborted(
		signal
	);


	throw new Error(
		`Agent exceeded ${modelConfig.maxAgentTurns} turns.`
	);
}