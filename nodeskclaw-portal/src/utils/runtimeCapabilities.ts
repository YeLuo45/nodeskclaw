import { reactive } from 'vue'

export interface RuntimeCapabilities {
  genes: boolean
  evolutionLog: boolean
  llmConfig: boolean
  channelConfig: boolean
  channelPluginDiscovery: boolean
  repoChannelSync: boolean
  npmChannelInstall: boolean
  uploadChannelPlugin: boolean
  gateway: boolean
  healthEndpoint: boolean
  configEndpoint: boolean
  webUi: boolean
  backup: boolean
  runtimeConfigPatch: boolean
  toolAllow: boolean
  dataRoot: string
}

export interface RuntimeEnginePayload {
  runtime_id: string
  data_dir_container_path?: string | null
  config_rel_path?: string | null
  capabilities?: Record<string, boolean> | null
}

export interface RuntimeDefaultCapability {
  id: string
  labelKey: string
  descriptionKey: string
}

const MINIMAL_CAPS: RuntimeCapabilities = {
  genes: false,
  evolutionLog: false,
  llmConfig: false,
  channelConfig: false,
  channelPluginDiscovery: false,
  repoChannelSync: false,
  npmChannelInstall: false,
  uploadChannelPlugin: false,
  gateway: false,
  healthEndpoint: false,
  configEndpoint: false,
  webUi: false,
  backup: false,
  runtimeConfigPatch: false,
  toolAllow: false,
  dataRoot: '',
}

const LEGACY_CAPS: Record<string, RuntimeCapabilities> = {
  openclaw: {
    genes: true,
    evolutionLog: true,
    llmConfig: true,
    channelConfig: true,
    channelPluginDiscovery: true,
    repoChannelSync: true,
    npmChannelInstall: true,
    uploadChannelPlugin: true,
    gateway: true,
    healthEndpoint: true,
    configEndpoint: true,
    webUi: true,
    backup: true,
    runtimeConfigPatch: true,
    toolAllow: true,
    dataRoot: '.openclaw',
  },
  hermes: {
    genes: true,
    evolutionLog: false,
    llmConfig: true,
    channelConfig: true,
    channelPluginDiscovery: false,
    repoChannelSync: false,
    npmChannelInstall: false,
    uploadChannelPlugin: false,
    gateway: true,
    healthEndpoint: true,
    configEndpoint: true,
    webUi: false,
    backup: true,
    runtimeConfigPatch: false,
    toolAllow: false,
    dataRoot: '.hermes',
  },
}

const DEFAULT_CAPABILITIES: Record<string, RuntimeDefaultCapability[]> = {
  hermes: [
    {
      id: 'shared-files',
      labelKey: 'runtimeDefaultCapabilities.sharedFiles',
      descriptionKey: 'runtimeDefaultCapabilities.sharedFilesDesc',
    },
    {
      id: 'blackboard',
      labelKey: 'runtimeDefaultCapabilities.blackboard',
      descriptionKey: 'runtimeDefaultCapabilities.blackboardDesc',
    },
    {
      id: 'topology',
      labelKey: 'runtimeDefaultCapabilities.topology',
      descriptionKey: 'runtimeDefaultCapabilities.topologyDesc',
    },
  ],
}

const runtimeCapsFromBackend = reactive<Record<string, RuntimeCapabilities>>({})

function boolFromBackend(
  raw: Record<string, boolean> | null | undefined,
  key: string,
  fallback: boolean,
): boolean {
  const value = raw?.[key]
  return typeof value === 'boolean' ? value : fallback
}

function dataRootFromEngine(engine: RuntimeEnginePayload, fallback: string): string {
  const configPath = engine.config_rel_path?.trim().replace(/^\/+/, '')
  const configRoot = configPath?.split('/')[0]
  if (configRoot) {
    return configRoot
  }
  const containerPath = engine.data_dir_container_path?.trim()
  if (containerPath) {
    return containerPath.replace(/^\/root\/?/, '').replace(/^\/+/, '').replace(/\/$/, '') || fallback
  }
  return fallback
}

function normalizeEngineCapabilities(engine: RuntimeEnginePayload): RuntimeCapabilities {
  const runtime = engine.runtime_id
  const fallback = LEGACY_CAPS[runtime] ?? MINIMAL_CAPS
  const raw = engine.capabilities
  return {
    genes: boolFromBackend(raw, 'genes', fallback.genes),
    evolutionLog: boolFromBackend(raw, 'evolution_log', fallback.evolutionLog),
    llmConfig: boolFromBackend(raw, 'llm_config', fallback.llmConfig),
    channelConfig: boolFromBackend(raw, 'channel_config', fallback.channelConfig),
    channelPluginDiscovery: boolFromBackend(raw, 'channel_plugin_discovery', fallback.channelPluginDiscovery),
    repoChannelSync: boolFromBackend(raw, 'repo_channel_sync', fallback.repoChannelSync),
    npmChannelInstall: boolFromBackend(raw, 'npm_channel_install', fallback.npmChannelInstall),
    uploadChannelPlugin: boolFromBackend(raw, 'upload_channel_plugin', fallback.uploadChannelPlugin),
    gateway: boolFromBackend(raw, 'gateway', fallback.gateway),
    healthEndpoint: boolFromBackend(raw, 'health_endpoint', fallback.healthEndpoint),
    configEndpoint: boolFromBackend(raw, 'config_endpoint', fallback.configEndpoint),
    webUi: boolFromBackend(raw, 'web_ui', fallback.webUi),
    backup: boolFromBackend(raw, 'backup', fallback.backup),
    runtimeConfigPatch: boolFromBackend(raw, 'runtime_config_patch', fallback.runtimeConfigPatch),
    toolAllow: boolFromBackend(raw, 'tool_allow', fallback.toolAllow),
    dataRoot: dataRootFromEngine(engine, fallback.dataRoot),
  }
}

export function setRuntimeEngines(engines: RuntimeEnginePayload[]): void {
  for (const engine of engines) {
    if (!engine.runtime_id) continue
    runtimeCapsFromBackend[engine.runtime_id] = normalizeEngineCapabilities(engine)
  }
}

export function resetRuntimeEnginesForTest(): void {
  for (const key of Object.keys(runtimeCapsFromBackend)) {
    delete runtimeCapsFromBackend[key]
  }
}

export function getRuntimeCaps(runtime: string): RuntimeCapabilities {
  return runtimeCapsFromBackend[runtime] ?? LEGACY_CAPS[runtime] ?? { ...MINIMAL_CAPS }
}

export function getRuntimeDefaultCapabilities(runtime: string): RuntimeDefaultCapability[] {
  return DEFAULT_CAPABILITIES[runtime] ?? []
}
