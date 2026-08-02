import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ResponseCard from '../../src/components/chat/ResponseCard.vue'
import type { ChatMessage } from '../../src/stores/chat'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('ResponseCard', () => {
  const baseMessage: ChatMessage = {
    id: 'msg_1',
    role: 'assistant',
    content: 'Respuesta de prueba',
    timestamp: Date.now(),
    sources: [],
    metrics: {
      similarity: 0.87,
      numSources: 4,
      coverage: 100,
      latency: 2100,
      tokens: 1800,
      model: 'bge-m3 + llama',
    },
  }

  it('renders assistant message with content', () => {
    const wrapper = mount(ResponseCard, {
      props: { message: baseMessage, isSelected: false },
    })
    expect(wrapper.text()).toContain('Respuesta de prueba')
  })

  it('shows user message without selection styling', () => {
    const userMessage: ChatMessage = {
      id: 'msg_2',
      role: 'user',
      content: 'Pregunta de prueba',
      timestamp: Date.now(),
    }
    const wrapper = mount(ResponseCard, {
      props: { message: userMessage, isSelected: false },
    })
    expect(wrapper.text()).toContain('Pregunta de prueba')
    expect(wrapper.find('.border-red-900').exists()).toBe(false)
  })

  it('shows selected styling when isSelected is true', () => {
    const wrapper = mount(ResponseCard, {
      props: { message: baseMessage, isSelected: true },
    })
    expect(wrapper.find('.border-red-900').exists()).toBe(true)
    expect(wrapper.text()).toContain('Respuesta seleccionada')
  })

  it('shows metric chips for assistant message', () => {
    const wrapper = mount(ResponseCard, {
      props: { message: baseMessage, isSelected: false },
    })
    expect(wrapper.text()).toContain('similitud 0.87')
    expect(wrapper.text()).toContain('4 fuentes')
    expect(wrapper.text()).toContain('cobertura citas 100%')
  })

  it('emits select event when assistant card clicked', async () => {
    const wrapper = mount(ResponseCard, {
      props: { message: baseMessage, isSelected: false },
    })
    await wrapper.trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual(['msg_1'])
  })

  it('does not emit select for user message', async () => {
    const userMessage: ChatMessage = {
      id: 'msg_2',
      role: 'user',
      content: 'Pregunta',
      timestamp: Date.now(),
    }
    const wrapper = mount(ResponseCard, {
      props: { message: userMessage, isSelected: false },
    })
    await wrapper.trigger('click')
    expect(wrapper.emitted('select')).toBeFalsy()
  })
})
