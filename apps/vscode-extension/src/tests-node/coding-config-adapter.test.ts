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
	'0.7D3A Coding Agent uses only its new inference profile',
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
					): T => (
						settings.has(name)
							? settings.get(name)
							: fallback
					) as T
				})
			}
		};

		const loader =
			require('node:module') as ModuleLoader;

		const originalLoad =
			loader._load;

		let modelModule:
			typeof import('../model/ModelConfig');

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

			modelModule =
				require('../model/ModelConfig') as
					typeof import('../model/ModelConfig');
		} finally {
			loader._load = originalLoad;
		}

		const secrets = {
			get: async (
				key: string
			): Promise<string | undefined> =>
				storedSecrets.get(key),

			store: async (
				key: string,
				value: string
			): Promise<void> => {
				storedSecrets.set(key, value);
			},

			delete: async (
				key: string
			): Promise<void> => {
				storedSecrets.delete(key);
			}
		} as unknown as vscode.SecretStorage;

		const service =
			new modelModule.ModelConfigService(
				secrets
			);

		// Existing user settings and credential must
		// not silently override the new Coding profile.
		settings.set(
			'model.baseUrl',
			'legacy-endpoint'
		);

		settings.set(
			'model.name',
			'legacy-model'
		);

		storedSecrets.set(
			'agentStudio.model.apiKey',
			'legacy-synthetic-key'
		);

		const defaults =
			await service.getConfig();

		assert.equal(
			defaults.model,
			'gemma-4-12b-it-qat'
		);

		assert.equal(
			defaults.baseUrl,
			[
				'http:',
				'',
				'127.0.0.1:11433',
				'v1'
			].join('/')
		);

		assert.equal(
			defaults.apiKey,
			undefined
		);

		assert.equal(
			await service.hasApiKey(),
			false
		);

		// A Coding profile override must take effect.
		settings.set(
			'agents.coding.model',
			'custom-coding-model'
		);

		settings.set(
			'agents.coding.baseUrl',
			[
				'http:',
				'',
				'127.0.0.1:19000',
				'v1'
			].join('/')
		);

		await service.setApiKey(
			'new-synthetic-key'
		);

		const configured =
			await service.getConfig();

		assert.equal(
			configured.model,
			'custom-coding-model'
		);

		assert.equal(
			new URL(
				configured.baseUrl
			).port,
			'19000'
		);

		assert.equal(
			configured.apiKey,
			'new-synthetic-key'
		);

		assert.equal(
			await service.hasApiKey(),
			true
		);

		assert.equal(
			storedSecrets.get(
				'agentStudio.model.apiKey'
			),
			'legacy-synthetic-key'
		);

		await service.clearApiKey();

		assert.equal(
			await service.hasApiKey(),
			false
		);

		assert.equal(
			storedSecrets.get(
				'agentStudio.model.apiKey'
			),
			'legacy-synthetic-key'
		);

		settings.set(
			'agents.coding.enabled',
			false
		);

		await assert.rejects(
			service.getConfig(),
			/agent is disabled/
		);
	}
);
