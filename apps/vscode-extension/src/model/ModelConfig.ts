import type * as vscode from 'vscode';

import {
	AgentInferenceConfigService
} from './AgentInferenceConfig';

export interface ModelRuntimeConfig {
	baseUrl: string;
	model: string;
	apiKey?: string;
	temperature: number;
	maxTokens: number;
	timeoutSeconds: number;
	maxAgentTurns: number;
}

/**
 * Compatibility interface for the existing Coding Agent.
 *
 * The authoritative Coding Agent connection now lives at:
 *
 * agentStudio.agents.coding.*
 *
 * Other agent profiles are accessed through
 * AgentInferenceConfigService directly.
 */
export class ModelConfigService {
	private readonly inference:
		AgentInferenceConfigService;

	public constructor(
		secrets: vscode.SecretStorage
	) {
		this.inference =
			new AgentInferenceConfigService(
				secrets
			);
	}

	public async getConfig():
		Promise<ModelRuntimeConfig> {
		return this.inference.getConfig(
			'coding'
		);
	}

	public async setApiKey(
		apiKey: string
	): Promise<void> {
		await this.inference.setApiKey(
			'coding',
			apiKey
		);
	}

	public async clearApiKey():
		Promise<void> {
		await this.inference.clearApiKey(
			'coding'
		);
	}

	public async hasApiKey():
		Promise<boolean> {
		const profile =
			await this.inference
				.getPublicProfile(
					'coding'
				);

		return profile.hasApiKey;
	}
}
