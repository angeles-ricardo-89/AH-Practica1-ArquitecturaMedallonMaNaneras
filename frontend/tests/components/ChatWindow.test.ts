import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ChatWindow from '../../src/components/chat/ChatWindow.vue'
import { useChatStore } from '../../src/stores/chat'
import { useDashboardStore } from '../../src/stores/dashboard'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('ChatWindow', () => {
  it('renders input and submit button', () => {
    const wrapper = mount(ChatWindow)
    expect(wrapper.find('input').exists()).toBe(true)
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('clears input on submit', async () => {
    const wrapper = mount(ChatWindow)
    const input = wrapper.find('input')
    await input.setValue('Hola')
    await wrapper.find('form').trigger('submit.prevent')

    expect((input.element as HTMLInputElement).value).toBe('')
  })

  it('disables button when loading', () => {
    const store = useChatStore()
    store.isLoading = true

    const wrapper = mount(ChatWindow)
    const button = wrapper.find('button')
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('deselects response before sending message', async () => {
    const dashboardStore = useDashboardStore()
    dashboardStore.selectResponse('msg_123')
    const deselectSpy = vi.spyOn(dashboardStore, 'selectResponse')

    const wrapper = mount(ChatWindow)
    const input = wrapper.find('input')
    await input.setValue('Nueva pregunta')
    await wrapper.find('form').trigger('submit.prevent')

    expect(deselectSpy).toHaveBeenCalledWith(null)
  })

  it('deselects response on background click', async () => {
    const dashboardStore = useDashboardStore()
    dashboardStore.selectResponse('msg_123')
    const deselectSpy = vi.spyOn(dashboardStore, 'selectResponse')

    const wrapper = mount(ChatWindow)
    const container = wrapper.find('[ref="messagesContainer"]')
    const messagesContainer = container.exists() ? container : wrapper.find('.flex-1.overflow-y-auto')

    await messagesContainer.trigger('click')

    expect(deselectSpy).toHaveBeenCalledWith(null)
  })
})
