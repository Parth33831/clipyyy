import fs from 'node:fs'
import path from 'node:path'
import { GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { getSignedUrl } from '@aws-sdk/s3-request-presigner'
import { createPost, getClip, getSetting } from './store.js'
import type { PostRecord, PublishMode } from './types.js'

const BUFFER_URL = 'https://api.buffer.com'

export class PublishError extends Error {}

export function storageConfigured(): boolean {
  return Boolean(getSetting('s3_bucket') && getSetting('s3_access_key_id') && getSetting('s3_secret_access_key'))
}

export async function uploadPublic(filePath: string, key: string): Promise<string> {
  if (!storageConfigured()) {
    throw new PublishError('Set up S3-compatible storage in Settings so Buffer can fetch the video')
  }
  const bucket = getSetting('s3_bucket')
  const client = new S3Client({
    endpoint: getSetting('s3_endpoint_url') || undefined,
    region: getSetting('s3_region') || 'auto',
    credentials: {
      accessKeyId: getSetting('s3_access_key_id'),
      secretAccessKey: getSetting('s3_secret_access_key'),
    },
    forcePathStyle: Boolean(getSetting('s3_endpoint_url')),
  })
  const body = fs.readFileSync(filePath)
  await client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: body,
      ContentType: 'video/mp4',
    }),
  )
  const base = getSetting('s3_public_base_url').replace(/\/+$/, '')
  if (base) return `${base}/${key}`
  return getSignedUrl(client, new GetObjectCommand({ Bucket: bucket, Key: key }), { expiresIn: 7 * 24 * 3600 })
}

export class BufferClient {
  private apiKey: string

  constructor(apiKey?: string) {
    const resolved = apiKey ?? getSetting('buffer_api_key')
    if (!resolved) throw new PublishError('Add your Buffer API key in Settings to publish')
    this.apiKey = resolved
  }

  async query<T = Record<string, unknown>>(gql: string, variables: Record<string, unknown> = {}): Promise<T> {
    const res = await fetch(BUFFER_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query: gql, variables }),
      signal: AbortSignal.timeout(60_000),
    })
    const text = await res.text()
    if (!res.ok) throw new PublishError(`Buffer error ${res.status}: ${text.slice(0, 300)}`)
    const payload = JSON.parse(text) as { errors?: { message?: string }[]; data?: T }
    if (payload.errors?.length) {
      throw new PublishError(`Buffer error: ${payload.errors[0].message ?? 'Unknown error'}`)
    }
    return payload.data as T
  }

  async organizations(): Promise<{ id: string; name: string }[]> {
    const data = await this.query<{ account: { organizations: { id: string; name: string }[] } }>(
      'query { account { organizations { id name } } }',
    )
    return data.account.organizations
  }

  async organizationId(): Promise<string> {
    const configured = getSetting('buffer_organization_id')
    if (configured) return configured
    const orgs = await this.organizations()
    if (!orgs.length) throw new PublishError('Your Buffer account has no organizations')
    return orgs[0].id
  }

  async channels(): Promise<{ id: string; name: string; service: string; avatar: string }[]> {
    const orgId = await this.organizationId()
    const data = await this.query<{ channels: { id: string; name: string; service: string; avatar: string }[] }>(
      'query Channels($id: OrganizationId!) { channels(input: {organizationId: $id}) { id name service avatar } }',
      { id: orgId },
    )
    return data.channels
  }

  async createPost(
    channelId: string,
    service: string,
    text: string,
    videoUrl: string,
    title: string,
    mode: PublishMode,
    scheduledAt?: string | null,
  ): Promise<string> {
    const post: Record<string, unknown> = {
      channelId,
      text,
      schedulingType: 'automatic',
      assets: [{ video: { url: videoUrl } }],
    }
    if (mode === 'draft') {
      post.mode = 'addToQueue'
      post.saveToDraft = true
    } else if (mode === 'schedule') {
      if (!scheduledAt) throw new PublishError('Pick a time to schedule the post')
      post.mode = 'customScheduled'
      post.dueAt = scheduledAt
    } else {
      post.mode = mode === 'now' ? 'shareNow' : 'addToQueue'
    }

    const meta = platformMetadata(service, title)
    if (meta) post.metadata = meta

    const data = await this.query<{
      createPost: { __typename?: string; message?: string; post?: { id: string; status: string } }
    }>(
      'mutation CreatePost($input: CreatePostInput!) { createPost(input: $input) { __typename ... on PostActionSuccess { post { id status } } ... on MutationError { message } } }',
      { input: post },
    )
    if (data.createPost.__typename !== 'PostActionSuccess' || !data.createPost.post) {
      throw new PublishError(data.createPost.message || `Buffer returned ${data.createPost.__typename}`)
    }
    return data.createPost.post.id
  }
}

function platformMetadata(service: string, title: string): Record<string, unknown> | null {
  if (service === 'youtube') {
    return {
      youtube: {
        title: title.slice(0, 100),
        categoryId: '22',
        privacy: 'public',
        madeForKids: false,
        notifySubscribers: true,
        embeddable: true,
        license: 'youtube',
      },
    }
  }
  if (service === 'instagram') return { instagram: { type: 'reel', shouldShareToFeed: true } }
  if (service === 'facebook') return { facebook: { type: 'reel' } }
  return null
}

export async function publishClip(
  clipId: string,
  channelIds: string[],
  mode: PublishMode = 'queue',
  scheduledAt?: string | null,
  text?: string,
  title?: string,
): Promise<PostRecord[]> {
  const clip = getClip(clipId)
  if (!clip || clip.status !== 'ready' || !clip.file_path) {
    throw new PublishError('That clip is not ready to publish')
  }
  const client = new BufferClient()
  const channelsList = await client.channels()
  const channels = new Map(channelsList.map((c) => [c.id, c]))
  const unknown = channelIds.filter((id) => !channels.has(id))
  if (unknown.length) {
    throw new PublishError(`Unknown Buffer channel(s): ${unknown.join(', ')}`)
  }

  const filename = path.basename(clip.file_path)
  const mediaUrl = await uploadPublic(clip.file_path, `clipyyy/${clip.run_id}/${filename}`)
  const results: PostRecord[] = []
  const defaultText = clip.hashtags.length ? `${clip.caption}\n\n${clip.hashtags.join(' ')}`.trim() : clip.caption

  for (const channelId of channelIds) {
    const channel = channels.get(channelId)!
    const baseRecord = {
      clip_id: clipId,
      channel_id: channelId,
      channel_name: channel.name,
      service: channel.service,
      mode,
      media_url: mediaUrl,
      scheduled_at: scheduledAt ?? null,
    }
    try {
      const postId = await client.createPost(
        channelId,
        channel.service,
        text || defaultText,
        mediaUrl,
        title || clip.post_title || clip.title,
        mode,
        scheduledAt,
      )
      results.push(createPost({ ...baseRecord, status: 'sent_to_buffer', buffer_post_id: postId, error: null }))
    } catch (err) {
      results.push(
        createPost({
          ...baseRecord,
          status: 'failed',
          error: err instanceof Error ? err.message : String(err),
        }),
      )
    }
  }
  return results
}
