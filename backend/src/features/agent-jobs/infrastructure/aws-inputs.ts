import { createHash } from 'node:crypto';
import { DeleteObjectCommand, GetObjectCommand, HeadObjectCommand, type S3Client } from '@aws-sdk/client-s3';
import { createPresignedPost } from '@aws-sdk/s3-presigned-post';
import {
  DetectDocumentTextCommand,
  GetDocumentTextDetectionCommand,
  StartDocumentTextDetectionCommand,
  type Block,
  type TextractClient,
} from '@aws-sdk/client-textract';
import {
  DeleteTranscriptionJobCommand,
  GetTranscriptionJobCommand,
  StartTranscriptionJobCommand,
  type TranscribeClient,
} from '@aws-sdk/client-transcribe';
import type { AudioFormat, DocumentReader, DocumentReadIdentity, Transcriber, UploadStore } from '../ports.js';

export class S3UploadStore implements UploadStore {
  constructor(
    private readonly client: S3Client,
    readonly bucket: string,
  ) {}

  async presignPost(key: string, contentType: string, maxBytes: number, expiresSeconds: number) {
    // A presigned POST lets S3 itself enforce the size range and exact content type.
    const { url, fields } = await createPresignedPost(this.client, {
      Bucket: this.bucket,
      Key: key,
      Conditions: [
        ['content-length-range', 1, maxBytes],
        ['eq', '$Content-Type', contentType],
      ],
      Fields: { 'Content-Type': contentType },
      Expires: expiresSeconds,
    });
    return { url, fields };
  }

  async head(key: string) {
    try {
      const output = await this.client.send(new HeadObjectCommand({ Bucket: this.bucket, Key: key }));
      return { sizeBytes: output.ContentLength ?? 0, contentType: output.ContentType ?? null };
    } catch (error) {
      if (error instanceof Error && (error.name === 'NotFound' || error.name === 'NoSuchKey')) return null;
      throw error;
    }
  }

  async firstBytes(key: string, count: number) {
    const output = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key, Range: `bytes=0-${count - 1}` }));
    return output.Body ? await output.Body.transformToByteArray() : new Uint8Array();
  }

  async remove(key: string) {
    await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: key }));
  }
}

/** Amazon Transcribe batch jobs. Output stays in Transcribe's own storage and is deleted after reading. */
export class AwsTranscriber implements Transcriber {
  constructor(
    private readonly client: TranscribeClient,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async start(name: string, s3Uri: string, format: AudioFormat = 'm4a') {
    await this.client.send(
      new StartTranscriptionJobCommand({ TranscriptionJobName: name, LanguageCode: 'en-US', MediaFormat: format, Media: { MediaFileUri: s3Uri } }),
    );
  }

  async get(name: string) {
    const output = await this.client.send(new GetTranscriptionJobCommand({ TranscriptionJobName: name }));
    const job = output.TranscriptionJob;
    return {
      status: (job?.TranscriptionJobStatus ?? 'FAILED') as 'QUEUED' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED',
      ...(job?.Transcript?.TranscriptFileUri ? { transcriptUri: job.Transcript.TranscriptFileUri } : {}),
      ...(job?.FailureReason ? { failureReason: job.FailureReason } : {}),
    };
  }

  async fetchTranscript(uri: string) {
    const response = await this.fetchImpl(uri);
    if (!response.ok) throw new Error(`Transcript download failed: ${response.status}`);
    const json = (await response.json()) as { results?: { transcripts?: { transcript?: string }[] } };
    return (json.results?.transcripts ?? []).map((t) => t.transcript ?? '').join(' ').trim();
  }

  async remove(name: string) {
    await this.client.send(new DeleteTranscriptionJobCommand({ TranscriptionJobName: name })).catch(() => undefined);
  }
}

/** Amazon Textract synchronous text detection (single-page PDF, JPEG or PNG). */
/** Pages read from a multi-page PDF; estimates and benefit summaries put the numbers up front. */
export const MAX_PDF_PAGES = 5;

/**
 * Text lines of an image or PDF. Images and single-page PDFs use the instant API; a multi-page PDF
 * (which that API rejects) falls back to the asynchronous API. An elapsed time budget stops
 * further result requests; it cannot cancel an SDK request already in flight.
 */
export class TextractReader implements DocumentReader {
  constructor(
    private readonly client: Pick<TextractClient, 'send'>,
    private readonly options: { sleep?: (ms: number) => Promise<void>; now?: () => number; maxWaitMs?: number } = {},
  ) {}

  async readLines(bucket: string, key: string, identity: DocumentReadIdentity) {
    if (!identity || typeof identity.jobId !== 'string' || !identity.jobId.trim() || identity.jobId.length > 64
      || typeof identity.documentId !== 'string' || !identity.documentId.trim() || identity.documentId.length > 64) {
      throw named('DocumentReadIdentityError', 'A stable document job identity is required');
    }
    // Stable across process restarts/redelivery; never include the attempt, clock or randomness.
    // Hash only identifies this logical request, not an immutable version of a mutable S3 object.
    const ClientRequestToken = createHash('sha256')
      .update(JSON.stringify(['actionbridge-textract-text-v1', identity.jobId, identity.documentId, bucket, key]))
      .digest('hex');
    const S3Object = { Bucket: bucket, Name: key };
    try {
      const output = await this.client.send(new DetectDocumentTextCommand({ Document: { S3Object } }));
      return lines(output.Blocks);
    } catch (error) {
      if (!(error instanceof Error && error.name === 'UnsupportedDocumentException')) throw error;
    }
    const sleep = this.options.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
    const now = this.options.now ?? Date.now;
    const deadline = now() + (this.options.maxWaitMs ?? 60_000);
    const { JobId } = await this.client.send(new StartDocumentTextDetectionCommand({ DocumentLocation: { S3Object }, ClientRequestToken }));
    if (!JobId) throw named('TextractResponseError', 'Document processing returned no job identifier');
    for (;;) {
      requireTimeRemaining();
      await sleep(1500);
      requireTimeRemaining();
      const first = await this.client.send(new GetDocumentTextDetectionCommand({ JobId, MaxResults: 1000 }));
      requireTimeRemaining();
      if (first.JobStatus === 'FAILED') throw named('UnsupportedDocumentException', first.StatusMessage ?? 'Textract could not read the document');
      if (first.JobStatus === 'SUCCEEDED' || first.JobStatus === 'PARTIAL_SUCCESS') {
        const found = lines(first.Blocks);
        let token = first.NextToken;
        let lastPage = Math.max(0, ...(first.Blocks ?? []).map((b) => b.Page ?? 0));
        const seenTokens = new Set<string>();
        // A result batch can end partway through page five. Continue until the next
        // page is observed; line filtering still excludes every page beyond the cap.
        while (token && lastPage <= MAX_PDF_PAGES) {
          if (seenTokens.has(token)) throw named('TextractResponseError', 'Document processing repeated a result cursor');
          seenTokens.add(token);
          requireTimeRemaining();
          const next = await this.client.send(new GetDocumentTextDetectionCommand({ JobId, MaxResults: 1000, NextToken: token }));
          requireTimeRemaining();
          if (next.JobStatus !== 'SUCCEEDED' && next.JobStatus !== 'PARTIAL_SUCCESS')
            throw named('TextractResponseError', 'Document processing returned incomplete paginated results');
          found.push(...lines(next.Blocks));
          lastPage = Math.max(lastPage, ...(next.Blocks ?? []).map((b) => b.Page ?? 0));
          token = next.NextToken;
        }
        return found;
      }
    }

    function requireTimeRemaining() {
      if (now() >= deadline) throw named('TextractTimeout', 'Reading the document took too long');
    }

    function lines(blocks: Block[] | undefined): string[] {
      return (blocks ?? [])
        .filter((b) => b.BlockType === 'LINE' && b.Text && (b.Page ?? 1) <= MAX_PDF_PAGES)
        .map((b) => b.Text as string);
    }
  }
}

function named(name: string, message: string): Error {
  const error = new Error(message);
  error.name = name;
  return error;
}
