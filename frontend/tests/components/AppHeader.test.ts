import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useObservabilityStore } from '../../src/stores/observability'
import AppHeader from '../../src/components/shared/AppHeader.vue'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('AppHeader', () => {
  it('renders title and subtitle', () => {
    const wrapper = mount(AppHeader)
    expect(wrapper.text()).toContain('Dashboard técnico')
    expect(wrapper.text()).toContain('pipeline · RAG · fuentes · embeddings')
  })

  it('shows sin datos when config is null', () => {
    const wrapper = mount(AppHeader)
    expect(wrapper.text()).toContain('sin datos')
  })

  it('shows config values when available', () => {
    const store = useObservabilityStore()
    store.config = {
      ambiente: 'laboratorio',
      version: 'v0.3.0',
      docker: true,
      modelos: { llm: 'gemma4', embedding: 'nomic-embed-text' },
    }
    store.layers = {
      layers: [],
      health_global: 'Healthy',
      ultima_corrida_global: '2026-08-01 18:42',
    }

    const wrapper = mount(AppHeader)
    expect(wrapper.text()).toContain('laboratorio')
    expect(wrapper.text()).toContain('v0.3.0')
    expect(wrapper.text()).toContain('2026-08-01 18:42')
    expect(wrapper.text()).toContain('Healthy')
  })

  it('shows health badge with correct color', () => {
    const store = useObservabilityStore()
    store.layers = {
      layers: [],
      health_global: 'Degraded',
      ultima_corrida_global: '',
    }

    const wrapper = mount(AppHeader)
    expect(wrapper.text()).toContain('Degraded')
    const badge = wrapper.find('.bg-amber-100')
    expect(badge.exists()).toBe(true)
  })

  it('calls manualRefresh when refresh button clicked', async () => {
    const store = useObservabilityStore()
    const spy = vi.spyOn(store, 'manualRefresh')

    const wrapper = mount(AppHeader)
    const refreshButton = wrapper.findAll('button').find((b) => b.text().includes('Refresh'))
    expect(refreshButton).toBeTruthy()
    await refreshButton!.trigger('click')
    expect(spy).toHaveBeenCalled()
  })
})
