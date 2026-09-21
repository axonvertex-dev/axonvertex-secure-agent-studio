import * as assert from 'node:assert/strict';
import { test } from 'node:test';

import {
	probeAgentConnection
} from '../model/AgentConnectionProbe';

test(
	'0.7D3A agent connection probe distinguishes model and authentication states',
	async () => {
		const config = {
			baseUrl: [
				'http:',
				'',
				'127.0.0.1:11433',
				'v1'
			].join('/'),
			model:
				'gemma-4-12b-it-qat',
			apiKey:
				'synthetic-test-key'
		};

		const success:
			typeof fetch =
			async (
				input,
				init
			) => {
				assert.equal(
					String(input),
					`${config.baseUrl}/models`
				);

				assert.equal(
					init?.method,
					'GET'
				);

				assert.equal(
					(
						init?.headers as
							Record<string, string>
					).Authorization,
					'Bearer synthetic-test-key'
				);

				return new Response(
					JSON.stringify({
						data: [{
							id: config.model
						}]
					}),
					{
						status: 200
					}
				);
			};

		assert.deepEqual(
			await probeAgentConnection(
				config,
				success
			),
			{
				state: 'CONNECTED'
			}
		);

		const mismatch:
			typeof fetch =
			async () =>
				new Response(
					JSON.stringify({
						data: [{
							id: 'different-model'
						}]
					}),
					{
						status: 200
					}
				);

		assert.deepEqual(
			await probeAgentConnection(
				config,
				mismatch
			),
			{
				state:
					'MODEL_MISMATCH'
			}
		);

		const unauthorized:
			typeof fetch =
			async () =>
				new Response(
					'Do not display remote body',
					{
						status: 401
					}
				);

		assert.deepEqual(
			await probeAgentConnection(
				config,
				unauthorized
			),
			{
				state:
					'UNAUTHORIZED',
				httpStatus: 401
			}
		);

		const invalid:
			typeof fetch =
			async () =>
				new Response(
					JSON.stringify({
						unexpected: true
					}),
					{
						status: 200
					}
				);

		assert.deepEqual(
			await probeAgentConnection(
				config,
				invalid
			),
			{
				state:
					'INVALID_RESPONSE'
			}
		);

		const unreachable:
			typeof fetch =
			async () => {
				throw new Error(
					'Remote exception containing synthetic-test-key'
				);
			};

		const result =
			await probeAgentConnection(
				config,
				unreachable
			);

		assert.deepEqual(
			result,
			{
				state: 'UNREACHABLE'
			}
		);

		assert.equal(
			JSON.stringify(
				result
			).includes(
				config.apiKey
			),
			false
		);
	}
);
