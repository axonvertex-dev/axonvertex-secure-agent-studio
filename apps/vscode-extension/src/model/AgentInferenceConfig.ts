import * as vscode from 'vscode';

import type {
	ModelRuntimeConfig
} from './ModelConfig';

export const AGENT_ROLES = [
	'coding',
	'detector',
	'evidence'
] as const;

export type AgentRole =
	typeof AGENT_ROLES[number];

interface AgentDefinition {
	label: string;
	baseUrl: string;
	model: string;
	node: string;
}

export const AGENT_DEFINITIONS:
	Record<AgentRole, AgentDefinition> = {
	coding: {
		label: 'Coding Agent',
		baseUrl: 'http://127.0.0.1:11433/v1',
		model: 'gemma-4-12b-it-qat',
		node: 'A'
	},
	detector: {
		label: 'Detector Agent',
		baseUrl: 'http://100.99.149.21:18184/v1',
		model: 'antares-1b',
		node: 'B'
	},
	evidence: {
		label: 'Evidence Agent',
		baseUrl: 'http://100.76.212.84:18183/v1',
		model: 'foundation-sec-8b-reasoning',
		node: 'C'
	}
};

export interface PublicAgentProfile {
	role: AgentRole;
	label: string;
	node: string;
	enabled: boolean;
	baseUrl: string;
	model: string;
	hasApiKey: boolean;
}

export class AgentInferenceConfigService {
	public constructor(
		private readonly secrets:
			vscode.SecretStorage
	) {}

	private getConfiguration():
		vscode.WorkspaceConfiguration {
		return vscode.workspace.getConfiguration(
			'agentStudio'
		);
	}

	private secretName(
		role: AgentRole
	): string {
		return `agentStudio.agents.${role}.apiKey`;
	}

	private getEndpoint(
		role: AgentRole
	): string {
		const configured =
			this.getConfiguration().get<string>(
				`agents.${role}.baseUrl`,
				AGENT_DEFINITIONS[role].baseUrl
			);

		const baseUrl =
			configured.trim().replace(/\/+$/, '');

		let parsed: URL;

		try {
			parsed = new URL(baseUrl);
		} catch {
			throw new Error(
				`${role}: invalid inference endpoint URL.`
			);
		}

		if (
			!['http:', 'https:'].includes(
				parsed.protocol
			) ||
			!parsed.hostname ||
			parsed.username ||
			parsed.password ||
			parsed.search ||
			parsed.hash
		) {
			throw new Error(
				`${role}: endpoint must be an HTTP(S) URL without embedded credentials, query or fragment.`
			);
		}

		return baseUrl;
	}

	public isEnabled(
		role: AgentRole
	): boolean {
		return this.getConfiguration()
			.get<boolean>(
				`agents.${role}.enabled`,
				true
			);
	}

	public async getPublicProfile(
		role: AgentRole
	): Promise<PublicAgentProfile> {
		const definition =
			AGENT_DEFINITIONS[role];

		const model =
			this.getConfiguration()
				.get<string>(
					`agents.${role}.model`,
					definition.model
				)
				.trim();

		return {
			role,
			label: definition.label,
			node: definition.node,
			enabled: this.isEnabled(role),
			baseUrl: this.getEndpoint(role),
			model,
			hasApiKey: Boolean(
				await this.secrets.get(
					this.secretName(role)
				)
			)
		};
	}

	public async getConfig(
		role: AgentRole
	): Promise<ModelRuntimeConfig> {
		const profile =
			await this.getPublicProfile(role);

		if (!profile.enabled) {
			throw new Error(
				`${role}: agent is disabled.`
			);
		}

		if (!profile.model) {
			throw new Error(
				`${role}: model identifier is empty.`
			);
		}

		const configuration =
			this.getConfiguration();

		return {
			baseUrl: profile.baseUrl,
			model: profile.model,
			apiKey:
				await this.secrets.get(
					this.secretName(role)
				),
			temperature:
				configuration.get<number>(
					'model.temperature',
					0.1
				),
			maxTokens:
				configuration.get<number>(
					'model.maxTokens',
					2048
				),
			timeoutSeconds:
				configuration.get<number>(
					'model.timeoutSeconds',
					600
				),
			maxAgentTurns:
				configuration.get<number>(
					'agent.maxTurns',
					16
				)
		};
	}


	public async migrateLegacyCodingKey():
		Promise<
			'MIGRATED' |
			'LEGACY_KEY_ABSENT' |
			'NEW_KEY_EXISTS'
		> {
		const destination =
			this.secretName('coding');

		if (await this.secrets.get(destination)) {
			return 'NEW_KEY_EXISTS';
		}

		const legacy =
			await this.secrets.get(
				'agentStudio.model.apiKey'
			);

		if (!legacy) {
			return 'LEGACY_KEY_ABSENT';
		}

		await this.secrets.store(
			destination,
			legacy
		);

		return 'MIGRATED';
	}

	public async setApiKey(
		role: AgentRole,
		apiKey: string
	): Promise<void> {
		const value = apiKey.trim();

		if (!value) {
			throw new Error(
				`${role}: API key cannot be empty.`
			);
		}

		await this.secrets.store(
			this.secretName(role),
			value
		);
	}

	public async clearApiKey(
		role: AgentRole
	): Promise<void> {
		await this.secrets.delete(
			this.secretName(role)
		);
	}
}
