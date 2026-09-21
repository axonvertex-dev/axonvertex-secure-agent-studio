import * as assert from 'node:assert/strict';
import { test } from 'node:test';

import type * as vscode from 'vscode';

interface ModuleLoader {
	_load: (
		request: string,
		parent: unknown,
		isMain: boolean
	) => unknown;
}

test(
	'0.7D3A independent agent inference profiles',
	async () => {
		const settings =
			new Map<string, unknown>();

		const storedSecrets =
			new Map<string, string>();

		const fakeVscode = {
			workspace: {
				getConfiguration: () => ({
					get: <T>(
						name: string,
						fallback: T
					): T => {
						return (
							settings.has(name)
								? settings.get(name)
								: fallback
						) as T;
					}
				})
			}
		};

		const loader =
			require('node:module') as ModuleLoader;

		const originalLoad =
			loader._load;

		let inferenceModule:
			typeof import(
				'../model/AgentInferenceConfig'
			);

		try {
			loader._load = (
				request,
				parent,
				isMain
			) => {
				if (request === 'vscode') {
					return fakeVscode;
				}

				return originalLoad.call(
					loader,
					request,
					parent,
					isMain
				);
			};

			inferenceModule =
				require(
					'../model/AgentInferenceConfig'
				) as typeof import(
					'../model/AgentInferenceConfig'
				);
		} finally {
			loader._load = originalLoad;
		}

		const secrets = {
			get: async (
				name: string
			): Promise<string | undefined> =>
				storedSecrets.get(name),

			store: async (
				name: string,
				value: string
			): Promise<void> => {
				storedSecrets.set(
					name,
					value
				);
			},

			delete: async (
				name: string
			): Promise<void> => {
				storedSecrets.delete(name);
			}
		} as unknown as vscode.SecretStorage;

		const service =
			new inferenceModule
				.AgentInferenceConfigService(
					secrets
				);

		const expected = {
			coding: {
				host: '127.0.0.1:11433',
				model: 'gemma-4-12b-it-qat'
			},
			detector: {
				host: '100.99.149.21:18184',
				model: 'antares-1b'
			},
			evidence: {
				host: '100.76.212.84:18183',
				model: 'foundation-sec-8b-reasoning'
			}
		};

		for (
			const role of
			inferenceModule.AGENT_ROLES
		) {
			const profile =
				await service.getPublicProfile(
					role
				);

			assert.equal(
				new URL(
					profile.baseUrl
				).host,
				expected[role].host
			);

			assert.equal(
				profile.model,
				expected[role].model
			);

			assert.equal(
				profile.enabled,
				true
			);

			assert.equal(
				profile.hasApiKey,
				false
			);

			assert.equal(
				Object.hasOwn(
					profile,
					'apiKey'
				),
				false
			);
		}

		await service.setApiKey(
			'coding',
			'coding-test-secret'
		);

		await service.setApiKey(
			'detector',
			'detector-test-secret'
		);

		await service.setApiKey(
			'evidence',
			'evidence-test-secret'
		);

		assert.equal(
			storedSecrets.size,
			3
		);

		for (
			const role of
			inferenceModule.AGENT_ROLES
		) {
			const profile =
				await service.getPublicProfile(
					role
				);

			assert.equal(
				profile.hasApiKey,
				true
			);

			assert.equal(
				JSON.stringify(
					profile
				).includes(
					'test-secret'
				),
				false
			);
		}

		assert.equal(
			(
				await service.getConfig(
					'coding'
				)
			).apiKey,
			'coding-test-secret'
		);

		assert.equal(
			(
				await service.getConfig(
					'detector'
				)
			).apiKey,
			'detector-test-secret'
		);

		assert.equal(
			(
				await service.getConfig(
					'evidence'
				)
			).apiKey,
			'evidence-test-secret'
		);


		// Migration never overwrites an existing new-profile key.
		assert.equal(
			await service.migrateLegacyCodingKey(),
			'NEW_KEY_EXISTS'
		);

		await service.clearApiKey('coding');

		assert.equal(
			await service.migrateLegacyCodingKey(),
			'LEGACY_KEY_ABSENT'
		);

		await secrets.store(
			'agentStudio.model.apiKey',
			'legacy-coding-test-secret'
		);

		assert.equal(
			await service.migrateLegacyCodingKey(),
			'MIGRATED'
		);

		assert.equal(
			(await service.getConfig('coding')).apiKey,
			'legacy-coding-test-secret'
		);

		assert.equal(
			await secrets.get(
				'agentStudio.model.apiKey'
			),
			'legacy-coding-test-secret'
		);

		await service.clearApiKey(
			'detector'
		);

		assert.equal(
			(
				await service.getPublicProfile(
					'detector'
				)
			).hasApiKey,
			false
		);

		assert.equal(
			(
				await service.getPublicProfile(
					'coding'
				)
			).hasApiKey,
			true
		);

		settings.set(
			'agents.detector.enabled',
			false
		);

		await assert.rejects(
			service.getConfig(
				'detector'
			),
			/agent is disabled/
		);

		settings.set(
			'agents.coding.baseUrl',
			'not-an-http-endpoint'
		);

		await assert.rejects(
			service.getConfig(
				'coding'
			),
			/invalid inference endpoint URL/
		);

		settings.set(
			'agents.coding.baseUrl',
			'http://user:password@localhost:11433/v1'
		);

		await assert.rejects(
			service.getConfig(
				'coding'
			),
			/without embedded credentials/
		);
	}
);
