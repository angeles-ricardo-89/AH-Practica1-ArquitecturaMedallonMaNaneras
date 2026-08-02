import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PipelineCard from '../../src/components/pipeline/PipelineCard.vue'
import type { LayerRun } from '../../src/api/observability'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('PipelineCard', () => {
  const bronzeLayer: LayerRun = {
    capa: 'bronze',
    status: 'Completo',
    run_id: 'run-20260801-1842-BR',
    duracion_seg: 98,
    records_in: 42,
    records_out: 42,
    dlq_count: 0,
    started_at: '2026-08-01T18:42:00',
    finished_at: '2026-08-01T18:43:38',
  }

  it('renders capa name and subtitle', () => {
    const wrapper = mount(PipelineCard, {
      props: { layer: bronzeLayer },
    })
    expect(wrapper.text()).toContain('Bronze')
    expect(wrapper.text()).toContain('Ingesta cruda')
  })

  it('shows status badge with correct color', () => {
    const wrapper = mount(PipelineCard, {
      props: { layer: bronzeLayer },
    })
    expect(wrapper.text()).toContain('Completo')
    const badge = wrapper.find('.bg-green-100')
    expect(badge.exists()).toBe(true)
  })

  it('shows run id and duration', () => {
    const wrapper = mount(PipelineCard, {
      props: { layer: bronzeLayer },
    })
    expect(wrapper.text()).toContain('run-20260801-1842-BR')
    expect(wrapper.text()).toContain('1m 38s')
  })

  it('emits click event when clicked', async () => {
    const wrapper = mount(PipelineCard, {
      props: { layer: bronzeLayer },
    })
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
  })

  it('handles running status', () => {
    const runningLayer: LayerRun = {
      ...bronzeLayer,
      status: 'En curso',
      duracion_seg: null,
    }
    const wrapper = mount(PipelineCard, {
      props: { layer: runningLayer },
    })
    expect(wrapper.text()).toContain('En curso')
    const badge = wrapper.find('.bg-blue-100')
    expect(badge.exists()).toBe(true)
  })

  it('handles failed status', () => {
    const failedLayer: LayerRun = {
      ...bronzeLayer,
      status: 'Falló',
    }
    const wrapper = mount(PipelineCard, {
      props: { layer: failedLayer },
    })
    expect(wrapper.text()).toContain('Falló')
    const badge = wrapper.find('.bg-red-100')
    expect(badge.exists()).toBe(true)
  })

  it('handles interrupted status', () => {
    const interruptedLayer: LayerRun = {
      ...bronzeLayer,
      status: 'interrupted',
    }
    const wrapper = mount(PipelineCard, {
      props: { layer: interruptedLayer },
    })
    expect(wrapper.text()).toContain('Interrumpido')
    const badge = wrapper.find('.bg-amber-100')
    expect(badge.exists()).toBe(true)
  })

  it('maps backend ok status to Completo', () => {
    const okLayer: LayerRun = { ...bronzeLayer, status: 'ok' }
    const wrapper = mount(PipelineCard, { props: { layer: okLayer } })
    expect(wrapper.text()).toContain('Completo')
    const badge = wrapper.find('.bg-green-100')
    expect(badge.exists()).toBe(true)
  })

  it('maps backend error status to Falló', () => {
    const errorLayer: LayerRun = { ...bronzeLayer, status: 'error' }
    const wrapper = mount(PipelineCard, { props: { layer: errorLayer } })
    expect(wrapper.text()).toContain('Falló')
    const badge = wrapper.find('.bg-red-100')
    expect(badge.exists()).toBe(true)
  })
})
