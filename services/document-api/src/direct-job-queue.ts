import { randomUUID } from 'node:crypto'

export interface JobQueue {
  enqueue(input: Record<string, unknown>): Promise<{ jobId: string }>
}

export class DirectHttpJobQueue implements JobQueue {
  private readonly targetUrl: string

  constructor(
    targetUrl: string,
    private readonly fetchImpl: typeof globalThis.fetch = globalThis.fetch.bind(globalThis),
  ) {
    const url = new URL(targetUrl)
    if (
      url.protocol !== 'http:'
      || (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost')
    ) {
      throw new Error('direct worker dispatch is restricted to localhost HTTP')
    }
    this.targetUrl = url.toString()
  }

  async enqueue(input: Record<string, unknown>): Promise<{ jobId: string }> {
    const jobId = `emulator-${randomUUID()}`
    const response = await this.fetchImpl(this.targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CloudTasks-TaskName': jobId,
      },
      body: JSON.stringify(input),
      cache: 'no-store',
    })
    const body = await response.text()
    if (!response.ok) {
      throw new Error(`direct worker dispatch failed: HTTP ${response.status} ${body.slice(0, 500)}`)
    }
    return { jobId }
  }
}
