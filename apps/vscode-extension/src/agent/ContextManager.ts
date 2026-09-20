import type {
	ChatMessage
} from '../model/OpenAICompatibleClient';


/*
 * ============================================================
 * CONTEXT POLICY
 * ============================================================
 *
 * Gemma backend:
 *
 *     hard context = 32,768 tokens
 *
 * Agent Studio deliberately operates below that limit.
 *
 * IMPORTANT:
 *
 * The request budget includes:
 *
 * - messages
 * - system prompts
 * - evidence
 * - tool schemas
 * - tool-call arguments
 *
 * It is NOT merely a messages budget.
 */

const DEFAULT_MAX_REQUEST_TOKENS =
	24_000;


/*
 * Conservative approximation for code + JSON + tool schemas.
 *
 * Using 3.5 chars/token was too optimistic for the actual
 * Gemma request representation.
 */

const CHARS_PER_TOKEN_ESTIMATE =
	1.8;


const REQUEST_OVERHEAD_TOKENS =
	512;


const MAX_TOOL_RESULT_CHARS =
	7_000;


const MAX_EVIDENCE_CHARS =
	3_500;


const MAX_STRING_CHARS =
	3_500;


const MAX_ARRAY_ITEMS =
	80;


const OLD_TOOL_RESULT_CHARS =
	1_200;


const AGGRESSIVE_TOOL_RESULT_CHARS =
	700;


const EXCLUDED_PATH_SEGMENTS =
[
	'/.git/',
	'/.venv/',
	'/venv/',
	'/node_modules/',
	'/__pycache__/',
	'/.pytest_cache/',
	'/.mypy_cache/',
	'/.ruff_cache/',
	'/dist/',
	'/build/',
	'/out/'
];


/*
 * ============================================================
 * PATH FILTERING
 * ============================================================
 */

function normalizePathString(
	value: string
): string {

	return value.replaceAll(
		'\\',
		'/'
	);
}


function isExcludedPath(
	value: string
): boolean {

	const normalized =
		'/' +
		normalizePathString(
			value
		).replace(
			/^\/+/,
			''
		);


	return EXCLUDED_PATH_SEGMENTS.some(
		segment =>
			normalized.includes(
				segment
			)
	);
}


/*
 * ============================================================
 * TEXT COMPACTION
 * ============================================================
 */

function clipText(
	value: string,
	maxChars: number
): string {

	if (
		value.length <=
			maxChars
	) {

		return value;
	}


	const marker =
		`\n...[Agent Studio compacted ${value.length - maxChars} characters]...\n`;


	const available =
		Math.max(
			0,
			maxChars -
			marker.length
		);


	const headChars =
		Math.floor(
			available *
			0.72
		);


	const tailChars =
		available -
		headChars;


	return (
		value.slice(
			0,
			headChars
		) +

		marker +

		value.slice(
			-tailChars
		)
	);
}


/*
 * ============================================================
 * STRUCTURED VALUE COMPACTION
 * ============================================================
 */

function compactValue(
	value: unknown,
	depth = 0
): unknown {

	if (
		depth > 6
	) {

		return '[nested value compacted]';
	}


	if (
		typeof value ===
			'string'
	) {

		if (
			isExcludedPath(
				value
			)
		) {

			return undefined;
		}


		return clipText(
			value,
			MAX_STRING_CHARS
		);
	}


	if (
		value === null ||
		typeof value ===
			'number' ||
		typeof value ===
			'boolean'
	) {

		return value;
	}


	if (
		Array.isArray(
			value
		)
	) {

		const compacted =
			value
				.map(
					item =>
						compactValue(
							item,
							depth + 1
						)
				)
				.filter(
					item =>
						item !==
							undefined
				);


		if (
			compacted.length <=
				MAX_ARRAY_ITEMS
		) {

			return compacted;
		}


		return [
			...compacted.slice(
				0,
				MAX_ARRAY_ITEMS
			),

			{
				contextCompacted:
					true,

				omittedItems:
					compacted.length -
					MAX_ARRAY_ITEMS
			}
		];
	}


	if (
		typeof value ===
			'object'
	) {

		const source =
			value as
				Record<
					string,
					unknown
				>;


		const result:
			Record<
				string,
				unknown
			> =
		{};


		for (
			const [
				key,
				item
			]
			of Object.entries(
				source
			)
		) {

			const compacted =
				compactValue(
					item,
					depth + 1
				);


			if (
				compacted !==
					undefined
			) {

				result[key] =
					compacted;
			}
		}


		return result;
	}


	return String(
		value
	);
}


/*
 * ============================================================
 * MESSAGE CLONING
 * ============================================================
 */

function cloneMessages(
	messages: ChatMessage[]
): ChatMessage[] {

	return JSON.parse(
		JSON.stringify(
			messages
		)
	) as ChatMessage[];
}


/*
 * ============================================================
 * TOOL OBSERVATION COMPACTION
 * ============================================================
 */

function compactToolMessages(
	messages: ChatMessage[],
	maxChars: number,
	preserveNewestToolMessages: number
): void {

	const toolIndexes:
		number[] =
		[];


	for (
		let index = 0;
		index < messages.length;
		index++
	) {

		if (
			messages[index].role ===
				'tool'
		) {

			toolIndexes.push(
				index
			);
		}
	}


	const preserveFrom =
		Math.max(
			0,
			toolIndexes.length -
				preserveNewestToolMessages
		);


	for (
		let position = 0;
		position < toolIndexes.length;
		position++
	) {

		if (
			position >=
				preserveFrom
		) {

			continue;
		}


		const message =
			messages[
				toolIndexes[
					position
				]
			];


		if (
			typeof message.content !==
				'string'
		) {

			continue;
		}


		message.content =
			clipText(
				message.content,
				maxChars
			);
	}
}


/*
 * ============================================================
 * TOOL CALL ARGUMENT COMPACTION
 * ============================================================
 *
 * Large proposed edits can themselves be huge because the assistant
 * message contains the complete tool-call arguments.
 *
 * Once older calls have executed, Agent Studio does not need to
 * resend their complete arguments forever.
 */

function compactAssistantToolCalls(
	messages: ChatMessage[],
	maxArgumentChars: number,
	preserveNewestAssistantCalls: number
): void {

	const assistantIndexes:
		number[] =
		[];


	for (
		let index = 0;
		index < messages.length;
		index++
	) {

		const record =
			messages[index] as unknown as
				Record<
					string,
					unknown
				>;


		if (
			record.role ===
				'assistant' &&
			Array.isArray(
				record.tool_calls
			) &&
			record.tool_calls.length >
				0
		) {

			assistantIndexes.push(
				index
			);
		}
	}


	const preserveFrom =
		Math.max(
			0,
			assistantIndexes.length -
				preserveNewestAssistantCalls
		);


	for (
		let position = 0;
		position <
			assistantIndexes.length;
		position++
	) {

		if (
			position >=
				preserveFrom
		) {

			continue;
		}


		const record =
			messages[
				assistantIndexes[
					position
				]
			] as unknown as
				Record<
					string,
					unknown
				>;


		const calls =
			record.tool_calls;


		if (
			!Array.isArray(
				calls
			)
		) {

			continue;
		}


		for (
			const rawCall
			of calls
		) {

			if (
				!rawCall ||
				typeof rawCall !==
					'object'
			) {

				continue;
			}


			const call =
				rawCall as
					Record<
						string,
						unknown
					>;


			const rawFunction =
				call.function;


			if (
				!rawFunction ||
				typeof rawFunction !==
					'object'
			) {

				continue;
			}


			const fn =
				rawFunction as
					Record<
						string,
						unknown
					>;


			if (
				typeof fn.arguments ===
					'string'
			) {

				fn.arguments =
					clipText(
						fn.arguments,
						maxArgumentChars
					);
			}
		}
	}
}


/*
 * ============================================================
 * REQUEST TOKEN ESTIMATION
 * ============================================================
 */

function estimateRequestTokens(
	messages: ChatMessage[],
	tools: unknown
): number {

	const serialized =
		JSON.stringify({
			messages,
			tools
		});


	return (
		Math.ceil(
			serialized.length /
				CHARS_PER_TOKEN_ESTIMATE
		) +
		REQUEST_OVERHEAD_TOKENS
	);
}


/*
 * ============================================================
 * CONTEXT MANAGER
 * ============================================================
 */

export class ContextManager {


	/*
	 * ========================================================
	 * COMPACT INDIVIDUAL TOOL RESULT
	 * ========================================================
	 */

	public compactToolResult(
		toolName: string,
		result: unknown
	): string {

		const compacted =
			compactValue(
				result
			);


		const serialized =
			JSON.stringify(
				compacted
			);


		if (
			serialized.length <=
				MAX_TOOL_RESULT_CHARS
		) {

			return serialized;
		}


		return JSON.stringify({
			contextCompacted:
				true,

			tool:
				toolName,

			preview:
				clipText(
					serialized,
					MAX_TOOL_RESULT_CHARS
				)
		});
	}


	/*
	 * ========================================================
	 * PUBLIC REQUEST ESTIMATE
	 * ========================================================
	 */

	public estimateRequestTokens(
		messages: ChatMessage[],
		tools: unknown
	): number {

		return estimateRequestTokens(
			messages,
			tools
		);
	}


	/*
	 * ========================================================
	 * PREPARE MODEL REQUEST
	 * ========================================================
	 */

	public prepareModelMessages(
		messages: ChatMessage[],
		evidenceContext: string,
		tools: unknown,
		maxRequestTokens =
			DEFAULT_MAX_REQUEST_TOKENS
	): ChatMessage[] {

		const prepared =
			cloneMessages(
				messages
			);


		prepared.push({
			role:
				'system',

			content:
				clipText(
					evidenceContext,
					MAX_EVIDENCE_CHARS
				)
		});


		/*
		 * ----------------------------------------------------
		 * PASS 0 — no additional history compression
		 * ----------------------------------------------------
		 */

		if (
			estimateRequestTokens(
				prepared,
				tools
			) <=
				maxRequestTokens
		) {

			return prepared;
		}


		/*
		 * ----------------------------------------------------
		 * PASS 1
		 *
		 * Compact older observations while preserving the
		 * newest two tool results.
		 * ----------------------------------------------------
		 */

		compactToolMessages(
			prepared,
			OLD_TOOL_RESULT_CHARS,
			2
		);


		compactAssistantToolCalls(
			prepared,
			1_000,
			2
		);


		if (
			estimateRequestTokens(
				prepared,
				tools
			) <=
				maxRequestTokens
		) {

			return prepared;
		}


		/*
		 * ----------------------------------------------------
		 * PASS 2
		 *
		 * Preserve only the newest complete tool observation.
		 * ----------------------------------------------------
		 */

		compactToolMessages(
			prepared,
			900,
			1
		);


		compactAssistantToolCalls(
			prepared,
			700,
			1
		);


		if (
			estimateRequestTokens(
				prepared,
				tools
			) <=
				maxRequestTokens
		) {

			return prepared;
		}


		/*
		 * ----------------------------------------------------
		 * PASS 3
		 *
		 * Compact all tool history, including the newest
		 * observation.
		 *
		 * The model can call read_file again if it requires
		 * additional source detail.
		 * ----------------------------------------------------
		 */

		compactToolMessages(
			prepared,
			AGGRESSIVE_TOOL_RESULT_CHARS,
			0
		);


		compactAssistantToolCalls(
			prepared,
			500,
			0
		);


		if (
			estimateRequestTokens(
				prepared,
				tools
			) <=
				maxRequestTokens
		) {

			return prepared;
		}


		/*
		 * ----------------------------------------------------
		 * PASS 4 — emergency deterministic compression
		 * ----------------------------------------------------
		 */

		compactToolMessages(
			prepared,
			350,
			0
		);


		compactAssistantToolCalls(
			prepared,
			250,
			0
		);


		const estimatedTokens =
			estimateRequestTokens(
				prepared,
				tools
			);


		if (
			estimatedTokens >
				maxRequestTokens
		) {

			throw new Error(
				[
					'Agent Studio context budget exceeded.',
					`Estimated complete request tokens: ${estimatedTokens}.`,
					`Safety budget: ${maxRequestTokens}.`,
					'The estimate includes messages and tool schemas.',
					'The fixed system/tool-schema footprint may need reduction.'
				].join(
					' '
				)
			);
		}


		return prepared;
	}
}
