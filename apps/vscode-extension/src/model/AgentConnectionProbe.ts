import type {
	ModelRuntimeConfig
} from './ModelConfig';

export type ConnectionState =
	| 'CONNECTED'
	| 'MODEL_MISMATCH'
	| 'UNAUTHORIZED'
	| 'HTTP_ERROR'
	| 'INVALID_RESPONSE'
	| 'UNREACHABLE';

export interface ConnectionProbeResult {
	state: ConnectionState;
	httpStatus?: number;
}

export async function probeAgentConnection(
	config: Pick<
		ModelRuntimeConfig,
		'baseUrl' | 'model' | 'apiKey'
	>,
	requester: typeof fetch = fetch
): Promise<ConnectionProbeResult> {
	const controller =
		new AbortController();

	const timeout =
		setTimeout(
			() => controller.abort(),
			15_000
		);

	try {
		const headers:
			Record<string, string> = {
				Accept: 'application/json'
			};

		if (config.apiKey) {
			headers.Authorization =
				`Bearer ${config.apiKey}`;
		}

		const response =
			await requester(
				`${config.baseUrl}/models`,
				{
					method: 'GET',
					headers,
					signal:
						controller.signal
				}
			);

		if (
			response.status === 401 ||
			response.status === 403
		) {
			return {
				state: 'UNAUTHORIZED',
				httpStatus:
					response.status
			};
		}

		if (!response.ok) {
			return {
				state: 'HTTP_ERROR',
				httpStatus:
					response.status
			};
		}

		let body: unknown;

		try {
			body =
				await response.json();
		} catch {
			return {
				state:
					'INVALID_RESPONSE'
			};
		}

		if (
			typeof body !== 'object' ||
			body === null ||
			!('data' in body) ||
			!Array.isArray(body.data)
		) {
			return {
				state:
					'INVALID_RESPONSE'
			};
		}

		const matches =
			body.data.some(
				(item: unknown) =>
					typeof item ===
						'object' &&
					item !== null &&
					'id' in item &&
					item.id ===
						config.model
			);

		return {
			state: matches
				? 'CONNECTED'
				: 'MODEL_MISMATCH'
		};
	} catch {
		// Remote exception messages and response bodies
		// are never returned to the settings UI.
		return {
			state: 'UNREACHABLE'
		};
	} finally {
		clearTimeout(
			timeout
		);
	}
}
