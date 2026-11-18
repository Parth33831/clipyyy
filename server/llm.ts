import fs from 'node:fs'
import { interpolateWords } from './media.js'
import { getSetting } from './store.js'
import type { Sentence, Transcript } from './types.js'

export class LLMError extends Error {
  retryable: boolean
  constructor(message: string, retryable = true) {
    super(message)
    this.retryable = retryable
  }
}

export interface ProviderSpec {
  name: string
  baseUrl: string
  keySetting: string
  headers: Record<string, string>
  local: boolean
}

export const PROVIDERS: Record<string, ProviderSpec> = {
  openrouter: {
    name: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    keySetting: 'openrouter_api_key',
    headers: {
      'HTTP-Referer': 'https://github.com/T3-Venture-Labs-Limited/clipyyy',
      'X-Title': 'clipyyy',
    },
    local: false,
  },
  gemini: {
    name: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    keySetting: 'gemini_api_key',
    headers: {},
    local: false,
  },
  ollama: {
    name: 'Ollama (local)',
    baseUrl: 'http://127.0.0.1:11434/v1',
    keySetting: '',
    headers: {},
    local: true,
  },
}

export class OpenAICompatibleLLM {
  provider: ProviderSpec
  apiKey: string
  model: string
  timeoutMs: number

  constructor(provider: ProviderSpec, apiKey: string, model: string) {
    if (provider.keySetting && !apiKey) {
      throw new LLMError(`No API key for ${provider.name}. Add it in Settings.`, false)
    }
    this.provider = provider
    this.apiKey = apiKey
    this.model = model
    this.timeoutMs = provider.local ? 120_000 : provider.name === 'Google Gemini' ? 600_000 : 300_000
  }

  async completeJson(system: string, user: string, schema: Record<string, unknown>, name: string): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {
      model: this.model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
      response_format: {
        type: 'json_schema',
        json_schema: { name, strict: true, schema },
      },
    }
    return this.executeChat(body)
  }

  async completeJsonWithImages(
    system: string,
    user: string,
    schema: Record<string, unknown>,
    name: string,
    images: { timestamp: number; path: string }[],
  ): Promise<Record<string, unknown>> {
    const content: Record<string, unknown>[] = [{ type: 'text', text: user }]
    for (const img of images) {
      const encoded = fs.readFileSync(img.path).toString('base64')
      content.push({ type: 'text', text: `Video frame at ${img.timestamp.toFixed(1)} seconds:` })
      content.push({
        type: 'image_url',
        image_url: { url: `data:image/jpeg;base64,${encoded}`, detail: 'low' },
      })
    }
    const body: Record<string, unknown> = {
      model: this.model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content },
      ],
      response_format: {
        type: 'json_schema',
        json_schema: { name, strict: true, schema },
      },
    }
    return this.executeChat(body)
  }

  private async executeChat(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    let response = await this.postWithFallback(body)
    let text = await response.text()
    if (response.status === 400 && text.includes('response_format')) {
      delete body.response_format
      response = await this.post(body)
      text = await response.text()
    }
    if (response.status >= 400) {
      throw new LLMError(`${this.provider.name} error ${response.status}: ${text.slice(0, 500)}`)
    }
    const payload = JSON.parse(text) as { error?: unknown; choices?: { message?: { content?: unknown } }[] }
    if (payload.error) {
      throw new LLMError(`${this.provider.name} error: ${JSON.stringify(payload.error)}`)
    }
    const content = payload.choices?.[0]?.message?.content
    if (content === undefined) {
      throw new LLMError(`Unexpected response from ${this.provider.name}: ${text.slice(0, 300)}`)
    }
    return parseJson(content)
  }

  private async postWithFallback(body: Record<string, unknown>): Promise<Response> {
    const response = await this.post(body)
    if (this.provider.name === 'Google Gemini' && response.status === 404) {
      const cloneText = await response.clone().text()
      if (cloneText.toLowerCase().includes('no longer available to new users')) {
        const fallback = 'gemini-3.8-flash'
        if (this.model !== fallback) {
          this.model = fallback
          body.model = fallback
          return this.post(body)
        }
      }
    }
    return response
  }

  private async post(body: Record<string, unknown>): Promise<Response> {
    const isGemini = this.provider.name === 'Google Gemini'
    const attempts = this.provider.local ? 1 : isGemini ? 6 : 4
    let delayMs = isGemini ? 3000 : 2000
    const retryable = new Set([429, 500, 502, 503, 504])

    for (let attempt = 0; attempt < attempts; attempt++) {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), this.timeoutMs)
      try {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
          ...this.provider.headers,
        }
        if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`
        const res = await fetch(`${this.provider.baseUrl}/chat/completions`, {
          method: 'POST',
          headers,
          body: JSON.stringify(body),
          signal: controller.signal,
        })
        clearTimeout(timer)
        if (!retryable.has(res.status) || attempt === attempts - 1) {
          return res
        }
        const retryAfter = Number(res.headers.get('Retry-After') || 0)
        const waitMs = Math.max(delayMs, Number.isFinite(retryAfter) ? Math.min(60_000, Math.max(0, retryAfter * 1000)) : 0)
        await sleep(waitMs)
      } catch (err) {
        clearTimeout(timer)
        if (err instanceof Error && err.name === 'AbortError') {
          throw new LLMError(`${this.provider.name} request timed out after the configured limit.`, false)
        }
        if (this.provider.local || attempt === attempts - 1) {
          throw new LLMError(`${this.provider.name} connection failed: ${err instanceof Error ? err.message : String(err)}`, !this.provider.local)
        }
        await sleep(delayMs)
      }
      delayMs = Math.min(delayMs * 2, 30_000)
    }
    throw new LLMError('Unreachable retry loop', false)
  }
}

export function parseJson(content: unknown): Record<string, unknown> {
  let raw = content
  if (Array.isArray(raw)) {
    raw = raw.map((p) => (p && typeof p === 'object' && 'text' in p ? String((p as { text?: unknown }).text ?? '') : '')).join('')
  }
  let text = String(raw ?? '').trim()
  if (text.startsWith('```')) {
    const firstNewline = text.indexOf('\n')
    if (firstNewline !== -1) text = text.slice(firstNewline + 1)
    const lastFence = text.lastIndexOf('```')
    if (lastFence !== -1) text = text.slice(0, lastFence)
  }
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start === -1 || end === -1 || end < start) {
    throw new LLMError(`Model did not return JSON: ${text.slice(0, 200)}`)
  }
  try {
    return JSON.parse(text.slice(start, end + 1)) as Record<string, unknown>
  } catch (err) {
    throw new LLMError(`Model returned invalid JSON: ${err instanceof Error ? err.message : String(err)}: ${text.slice(0, 200)}`)
  }
}

export function getLlm(model?: string | null): OpenAICompatibleLLM {
  const providerKey = getSetting('llm_provider') || 'openrouter'
  const provider = PROVIDERS[providerKey]
  if (!provider) {
    throw new LLMError(`Unknown LLM provider '${providerKey}'. Available: ${Object.keys(PROVIDERS).join(', ')}`, false)
  }
  let selectedModel = model || getSetting('llm_model') || 'google/gemini-3.8-flash'
  if (provider.local && (!selectedModel || selectedModel === 'google/gemini-3.8-flash')) {
    selectedModel = 'qwen2.5:1.5b'
  }
  if (providerKey === 'gemini' && selectedModel.startsWith('google/')) {
    selectedModel = selectedModel.slice('google/'.length)
  }
  const apiKey = provider.keySetting ? getSetting(provider.keySetting) : ''
  return new OpenAICompatibleLLM(provider, apiKey, selectedModel)
}

export async function listModels(): Promise<
  {
    id: string
    name: string
    context_length: number | null
    prompt_price_per_million: number | null
    completion_price_per_million: number | null
  }[]
> {
  const providerKey = getSetting('llm_provider') || 'openrouter'
  const provider = PROVIDERS[providerKey] ?? PROVIDERS.openrouter
  const headers: Record<string, string> = {}
  const key = provider.keySetting ? getSetting(provider.keySetting) : ''
  if (key) headers.Authorization = `Bearer ${key}`

  const res = await fetch(`${provider.baseUrl}/models`, {
    headers,
    signal: AbortSignal.timeout(provider.local ? 10_000 : 30_000),
  })
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} from ${provider.name}`)
  }
  const json = (await res.json()) as {
    data?: {
      id: string
      name?: string
      context_length?: number | null
      supported_parameters?: string[]
      pricing?: { prompt?: string | number; completion?: string | number }
    }[]
  }
  const models = []
  for (const item of json.data ?? []) {
    const params = item.supported_parameters ?? []
    if (item.id.endsWith(':batch')) continue
    if (params.length > 0 && !params.includes('structured_outputs') && !params.includes('response_format')) {
      continue
    }
    models.push({
      id: item.id,
      name: item.name ?? item.id,
      context_length: item.context_length ?? null,
      prompt_price_per_million: perMillion(item.pricing?.prompt),
      completion_price_per_million: perMillion(item.pricing?.completion),
    })
  }
  return models.sort((a, b) => a.id.localeCompare(b.id))
}

function perMillion(v: unknown): number | null {
  const n = Number(v)
  if (!Number.isFinite(n) || v === undefined || v === null || v === '') return null
  return Math.round(n * 1_000_000 * 10000) / 10000
}

/**
 * Transcribe MP3 audio using Gemini REST API when GEMINI_API_KEY is available.
 */
export async function transcribeAudioWithGemini(
  mp3Path: string,
  durationSeconds: number,
  language: string,
): Promise<Transcript | null> {
  const apiKey = getSetting('gemini_api_key')
  if (!apiKey) return null
  const stat = fs.statSync(mp3Path)
  if (stat.size > 18 * 1024 * 1024) return null

  const base64Audio = fs.readFileSync(mp3Path).toString('base64')
  const langHint = language && language !== 'auto' ? `Language hint: ${language}.` : 'Detect the spoken language automatically.'
  const model = 'gemini-2.5-flash'
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(apiKey)}`
  const body = {
    contents: [
      {
        parts: [
          {
            text: `Transcribe this audio accurately into timestamped sentences from 0 to ${durationSeconds.toFixed(1)} seconds. ${langHint} Return JSON only with keys "language" (ISO code) and "sentences" (array of {"start": number, "end": number, "text": string}). Ensure timestamps are strictly ascending within [0, ${durationSeconds.toFixed(1)}].`,
          },
          {
            inline_data: {
              mime_type: 'audio/mp3',
              data: base64Audio,
            },
          },
        ],
      },
    ],
    generationConfig: {
      responseMimeType: 'application/json',
    },
  }

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  })
  if (!res.ok) return null
  const data = (await res.json()) as {
    candidates?: { content?: { parts?: { text?: string }[] } }[]
  }
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text
  if (!text) return null
  const parsed = parseJson(text) as { language?: string; sentences?: { start?: number; end?: number; text?: string }[] }
  const sentences: Sentence[] = []
  for (const s of parsed.sentences ?? []) {
    const start = Math.max(0, Math.min(durationSeconds, Number(s.start)))
    const end = Math.max(start, Math.min(durationSeconds, Number(s.end)))
    const sentenceText = String(s.text ?? '').trim()
    if (sentenceText && end > start) {
      sentences.push({ start: Math.round(start * 1000) / 1000, end: Math.round(end * 1000) / 1000, text: sentenceText })
    }
  }
  if (!sentences.length) return null
  return {
    language: String(parsed.language || language || 'auto'),
    sentences,
    words: interpolateWords(sentences),
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
