import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ChatWindow from '../../src/components/chat/ChatWindow.vue'
import { useChatStore } from '../../src/stores/chat'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('ChatWindow', () => {
  it('renders input and submit button', () => {
    const wrapper = mount(ChatWindow)
    expect(wrapper.find('input').exists()).toBe(true)
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('sends message on submit', async () => {
    const store = useChatStore()
    const sendSpy = vi.spyOn(store, 'sendMessage')

    const wrapper = mount(ChatWindow)
    const input = wrapper.find('input')
    await input.setValue('Hola')
    await wrapper.find('form').trigger('submit.prevent')

    expect(sendSpy).toHaveBeenCalledWith('Hola')
  })

  it('disables button when loading', () => {
    const store = useChatStore()
    store.isLoading = true

    const wrapper = mount(ChatWindow)
    const button = wrapper.find('button')
    expect(button.attributes('disabled')).toBeDefined()
  })
})
