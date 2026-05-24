import { afterEach, describe, expect, it } from 'vitest'

import {
  getRuntimeCaps,
  resetRuntimeEnginesForTest,
  setRuntimeEngines,
} from './runtimeCapabilities'

describe('runtimeCapabilities', () => {
  afterEach(() => {
    resetRuntimeEnginesForTest()
  })

  it('falls back to a minimal safe capability set for unknown runtimes', () => {
    const caps = getRuntimeCaps('custom-runtime')

    expect(caps.genes).toBe(false)
    expect(caps.evolutionLog).toBe(false)
    expect(caps.llmConfig).toBe(false)
    expect(caps.npmChannelInstall).toBe(false)
    expect(caps.uploadChannelPlugin).toBe(false)
    expect(caps.dataRoot).toBe('')
  })

  it('uses backend capabilities when engines are provided', () => {
    setRuntimeEngines([
      {
        runtime_id: 'hermes',
        data_dir_container_path: '/root/.hermes',
        capabilities: {
          genes: true,
          evolution_log: false,
          llm_config: true,
          channel_config: true,
          channel_plugin_discovery: false,
          repo_channel_sync: false,
          npm_channel_install: false,
          upload_channel_plugin: false,
          gateway: true,
          health_endpoint: true,
          config_endpoint: true,
          web_ui: false,
          backup: true,
          runtime_config_patch: false,
          tool_allow: false,
        },
      },
    ])

    const caps = getRuntimeCaps('hermes')

    expect(caps.evolutionLog).toBe(false)
    expect(caps.toolAllow).toBe(false)
    expect(caps.runtimeConfigPatch).toBe(false)
    expect(caps.npmChannelInstall).toBe(false)
    expect(caps.dataRoot).toBe('.hermes')
  })

  it('keeps legacy known-runtime fallback for old backends', () => {
    const caps = getRuntimeCaps('openclaw')

    expect(caps.genes).toBe(true)
    expect(caps.toolAllow).toBe(true)
    expect(caps.repoChannelSync).toBe(true)
    expect(caps.dataRoot).toBe('.openclaw')
  })

  it('keeps Hermes evolution log disabled in the legacy fallback', () => {
    const caps = getRuntimeCaps('hermes')

    expect(caps.genes).toBe(true)
    expect(caps.evolutionLog).toBe(false)
    expect(caps.dataRoot).toBe('.hermes')
  })

  it('derives file browsing root from config path before container path', () => {
    setRuntimeEngines([
      {
        runtime_id: 'custom-runtime',
        data_dir_container_path: '/app/data',
        config_rel_path: '.custom/config.yaml',
        capabilities: {
          genes: true,
        },
      },
    ])

    const caps = getRuntimeCaps('custom-runtime')

    expect(caps.genes).toBe(true)
    expect(caps.dataRoot).toBe('.custom')
  })
})
