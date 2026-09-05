import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import DashboardPage from '../../src/components/dashboard/DashboardPage.vue'
import SourcesList from '../../src/components/inspector/SourcesList.vue'
import { useObservabilityStore } from '../../src/stores/observability'
import { useDashboardStore } from '../../src/stores/dashboard'
import { useChatStore } from '../../src/stores/chat'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('DashboardPage Integration', () => {
  it('renders 3-column layout with header, pipeline, chat, inspector', () => {
    const obsStore = useObservabilityStore()
    obsStore.layers = {
      layers: [
        {
          capa: 'bronze',
          status: 'Completo',
          run_id: 'run-test',
          duracion_seg: 60,
          records_in: 10,
          records_out: 10,
          dlq_count: 0,
          started_at: '2026-08-01T18:42:00',
          finished_at: '2026-08-01T18:43:00',
        },
      ],
      health_global: 'Healthy',
      ultima_corrida_global: '2026-08-01T18:42:00',
    }
    const wrapper = mount(DashboardPage)
    expect(wrapper.text()).toContain('Dashboard técnico')
    expect(wrapper.text()).toContain('Pipeline medallón')
    expect(wrapper.text()).toContain('Chat RAG')
    expect(wrapper.text()).toContain('Embeddings 3D')
    expect(wrapper.text()).toContain('Fuentes usadas')
  })

  it('shows pipeline data when layers are available', async () => {
    const obsStore = useObservabilityStore()
    obsStore.layers = {
      layers: [
        {
          capa: 'bronze',
          status: 'Completo',
          run_id: 'run-20260801-1842-BR',
          duracion_seg: 98,
          records_in: 42,
          records_out: 42,
          dlq_count: 0,
          started_at: '2026-08-01T18:42:00',
          finished_at: '2026-08-01T18:43:38',
        },
        {
          capa: 'silver',
          status: 'Completo',
          run_id: 'run-20260801-1844-SI',
          duracion_seg: 131,
          records_in: 42,
          records_out: 41,
          dlq_count: 1,
          started_at: '2026-08-01T18:44:00',
          finished_at: '2026-08-01T18:46:11',
        },
        {
          capa: 'gold',
          status: 'En curso',
          run_id: 'run-20260801-1847-GO',
          duracion_seg: null,
          records_in: 41,
          records_out: 0,
          dlq_count: 0,
          started_at: '2026-08-01T18:47:00',
          finished_at: null,
        },
      ],
      health_global: 'Degraded',
      ultima_corrida_global: '2026-08-01T18:47:00',
    }

    const wrapper = mount(DashboardPage)
    await nextTick()

    expect(wrapper.text()).toContain('Bronze')
    expect(wrapper.text()).toContain('Silver')
    expect(wrapper.text()).toContain('Gold')
    expect(wrapper.text()).toContain('Ingesta cruda')
    expect(wrapper.text()).toContain('Validación + limpieza')
    expect(wrapper.text()).toContain('En curso')
  })

  it('opens evidence modal when pipeline card is clicked', async () => {
    const obsStore = useObservabilityStore()
    obsStore.layers = {
      layers: [
        {
          capa: 'bronze',
          status: 'Completo',
          run_id: 'run-test',
          duracion_seg: 60,
          records_in: 10,
          records_out: 10,
          dlq_count: 0,
          started_at: '2026-08-01T18:42:00',
          finished_at: '2026-08-01T18:43:00',
        },
      ],
      health_global: 'Healthy',
      ultima_corrida_global: '2026-08-01T18:42:00',
    }

    const wrapper = mount(DashboardPage)
    await nextTick()

    const card = wrapper.findComponent({ name: 'PipelineCard' })
    expect(card.exists()).toBe(true)

    await card.trigger('click')
    await nextTick()

    const dashboardStore = useDashboardStore()
    expect(dashboardStore.modalCapa).toBe('bronze')

    expect(document.body.textContent).toContain('Modal de evidencia')
    expect(document.body.textContent).toContain('Fuente pública sin autenticación')
  })

  it('updates sources and highlights chunks when response is selected', async () => {
    const chatStore = useChatStore()
    chatStore.messages = [
      {
        id: 'msg_user_1',
        role: 'user',
        content: 'Pregunta de prueba',
        timestamp: Date.now(),
      },
      {
        id: 'msg_assistant_1',
        role: 'assistant',
        content: 'Respuesta con fuentes',
        timestamp: Date.now(),
        sources: [
          {
            conference_id: 'conf_001',
            conference_date: '2026-07-30',
            participant: 'Presidenta',
            chunk_text: 'Fragmento sobre vivienda',
            similarity: 0.87,
            conference_url: 'https://gob.mx',
            pregunta_activa: 'Conferencia de prensa del 30 de julio de 2026',
            qualitative_label: 'Alta',
            embedding_3d: [1, 2, 3],
          },
        ],
        metrics: {
          similarity: 0.87,
          numSources: 1,
          coverage: 100,
          latency: 1200,
          tokens: 800,
          model: 'test-model',
        },
      },
    ]

    const wrapper = mount(DashboardPage)
    await nextTick()

    // Initially shows empty state
    expect(wrapper.text()).toContain('Selecciona una respuesta del chat para ver fuentes usadas')

    // Select the assistant response
    const dashboardStore = useDashboardStore()
    dashboardStore.selectResponse('msg_assistant_1')
    await nextTick()

    // SourcesList should now render the source
    expect(wrapper.text()).toContain('Conferencia de prensa del 30 de julio de 2026')
    expect(wrapper.text()).toContain('0.87')
    expect(wrapper.text()).toContain('Alta')
  })

  async function mountWithSelectedResponse() {
    const chatStore = useChatStore()
    chatStore.messages = [
      {
        id: 'msg_user_1',
        role: 'user',
        content: 'Pregunta de prueba',
        timestamp: Date.now(),
      },
      {
        id: 'msg_assistant_1',
        role: 'assistant',
        content: 'Respuesta con fuentes',
        timestamp: Date.now(),
        sources: [
          {
            conference_id: 'conf_001',
            conference_date: '2026-07-30',
            participant: 'Presidenta',
            chunk_text: 'Fragmento sobre vivienda',
            similarity: 0.87,
            conference_url: 'https://gob.mx',
            pregunta_activa: 'Conferencia de prensa del 30 de julio de 2026',
            qualitative_label: 'Alta',
            embedding_3d: [1, 2, 3],
          },
        ],
        metrics: {
          similarity: 0.87,
          numSources: 1,
          coverage: 100,
          latency: 1200,
          tokens: 800,
          model: 'test-model',
        },
      },
    ]

    const wrapper = mount(DashboardPage, { attachTo: document.body })
    await nextTick()

    const dashboardStore = useDashboardStore()
    dashboardStore.selectResponse('msg_assistant_1')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    return { wrapper, dashboardStore }
  }

  it('keeps selection when clicking inside the inspector column', async () => {
    const { wrapper, dashboardStore } = await mountWithSelectedResponse()

    const embeddingsHeading = wrapper
      .findAll('h3')
      .find((h) => h.text().includes('Embeddings 3D'))
    expect(embeddingsHeading).toBeTruthy()
    await embeddingsHeading!.trigger('click')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    const resizer = wrapper.find('.cursor-ns-resize')
    expect(resizer.exists()).toBe(true)
    await resizer.trigger('click')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    const sourceCard = wrapper.findComponent(SourcesList).find('.rounded-xl')
    expect(sourceCard.exists()).toBe(true)
    await sourceCard.trigger('click')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    wrapper.unmount()
  })

  it('deselects when clicking outside chat and inspector', async () => {
    const { wrapper, dashboardStore } = await mountWithSelectedResponse()

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(dashboardStore.selectedResponseId).toBeNull()

    wrapper.unmount()
  })
})
