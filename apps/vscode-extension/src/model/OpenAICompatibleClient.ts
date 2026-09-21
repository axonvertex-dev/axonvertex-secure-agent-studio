import type {
	ModelRuntimeConfig
} from './ModelConfig';


export interface ChatMessage {

	role:
		| 'system'
		| 'user'
		| 'assistant'
		| 'tool';

	content?: string;

	tool_calls?: unknown[];

	tool_call_id?: string;
}


export interface ChatCompletionRequest {

	messages: ChatMessage[];

	tools?: unknown[];

	toolChoice?: string;

	signal?: AbortSignal;
}


export interface ChatCompletionResponse {

	choices?: Array<{

		message?: {

			role?: string;

			content?: string;

			reasoning_content?: string;

			tool_calls?: unknown[];
		};

	}>;
}


function createAbortError(): Error {

	const error =
		new Error(
			'Model request cancelled.'
		);


	error.name =
		'AbortError';


	return error;
}


export async function createChatCompletion(
	config: ModelRuntimeConfig,
	request: ChatCompletionRequest
): Promise<ChatCompletionResponse> {

	const timeoutController =
		new AbortController();


	const combinedController =
		new AbortController();


	const abort =
		() => {

			combinedController.abort();
		};


	const timeout =
		setTimeout(
			() => {

				timeoutController.abort();

			},
			config.timeoutSeconds *
				1000
		);


	request.signal?.addEventListener(
		'abort',
		abort,
		{
			once: true
		}
	);


	timeoutController.signal.addEventListener(
		'abort',
		abort,
		{
			once: true
		}
	);


	try {

		const headers:
			Record<string, string> =
		{
			'Content-Type':
				'application/json'
		};


		if (
			config.apiKey
		) {

			headers.Authorization =
				`Bearer ${config.apiKey}`;
		}


		const response =
			await fetch(
				`${config.baseUrl}/chat/completions`,
				{
					method:
						'POST',

					headers,

					body:
						JSON.stringify({
							model:
								config.model,

							messages:
								request.messages,

							tools:
								request.tools,

							tool_choice:
								request.toolChoice,

							temperature:
								config.temperature,

							max_tokens:
								config.maxTokens,

							stream:
								false
						}),

					signal:
						combinedController.signal
				}
			);


		if (
			!response.ok
		) {


			throw new Error(
				`Model HTTP ${response.status}`
			);
		}


		return (
			await response.json()
		) as ChatCompletionResponse;

	} catch (error) {

		if (
			combinedController.signal.aborted
		) {

			throw createAbortError();
		}


		throw error;

	} finally {

		clearTimeout(
			timeout
		);


		request.signal?.removeEventListener(
			'abort',
			abort
		);


		timeoutController.signal.removeEventListener(
			'abort',
			abort
		);
	}
}
