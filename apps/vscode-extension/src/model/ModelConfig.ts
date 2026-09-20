import * as vscode from 'vscode';


const CONFIG_SECTION =
	'agentStudio';


const API_KEY_SECRET =
	'agentStudio.model.apiKey';


export interface ModelRuntimeConfig {

	baseUrl: string;

	model: string;

	apiKey?: string;

	temperature: number;

	maxTokens: number;

	timeoutSeconds: number;

	maxAgentTurns: number;
}


export class ModelConfigService {


	public constructor(
		private readonly secrets:
			vscode.SecretStorage
	) {}


	public async getConfig():
		Promise<ModelRuntimeConfig> {

		const configuration =
			vscode.workspace.getConfiguration(
				CONFIG_SECTION
			);


		const baseUrl =
			configuration.get<string>(
				'model.baseUrl',
				'http://127.0.0.1:18190/v1'
			)
				.trim()
				.replace(
					/\/+$/,
					''
				);


		const model =
			configuration.get<string>(
				'model.name',
				'gemma4-31b-q4'
			)
				.trim();


		const temperature =
			configuration.get<number>(
				'model.temperature',
				0.1
			);


		const maxTokens =
			configuration.get<number>(
				'model.maxTokens',
				2048
			);


		const timeoutSeconds =
			configuration.get<number>(
				'model.timeoutSeconds',
				600
			);


		const maxAgentTurns =
			configuration.get<number>(
				'agent.maxTurns',
				16
			);


		const apiKey =
			await this.secrets.get(
				API_KEY_SECRET
			);


		if (!baseUrl) {

			throw new Error(
				'Agent Studio model endpoint is not configured.'
			);
		}


		if (!model) {

			throw new Error(
				'Agent Studio model name is not configured.'
			);
		}


		return {
			baseUrl,
			model,
			apiKey,
			temperature,
			maxTokens,
			timeoutSeconds,
			maxAgentTurns
		};
	}


	public async setApiKey(
		apiKey: string
	): Promise<void> {

		const value =
			apiKey.trim();


		if (!value) {

			throw new Error(
				'API key cannot be empty.'
			);
		}


		await this.secrets.store(
			API_KEY_SECRET,
			value
		);
	}


	public async clearApiKey():
		Promise<void> {

		await this.secrets.delete(
			API_KEY_SECRET
		);
	}


	public async hasApiKey():
		Promise<boolean> {

		return Boolean(
			await this.secrets.get(
				API_KEY_SECRET
			)
		);
	}
}
