import { describe, expect, it } from 'vitest';
import { MAX_PDF_PAGES, TextractReader } from '../src/features/agent-jobs/infrastructure/aws-inputs.js';
import type { DocumentReadIdentity } from '../src/features/agent-jobs/ports.js';

type Sent = { name: string; input: Record<string, unknown> };

/** A fake Textract client that answers by command name; records what was sent. */
function fakeClient(answer: (sent: Sent) => unknown) {
  const sent: Sent[] = [];
  return {
    sent,
    client: {
      send: async (command: { constructor: { name: string }; input: Record<string, unknown> }) => {
        const call = { name: command.constructor.name, input: command.input };
        sent.push(call);
        const result = answer(call);
        if (result instanceof Error) throw result;
        return result;
      },
    } as never,
  };
}

const unsupported = Object.assign(new Error('Request has unsupported document format'), { name: 'UnsupportedDocumentException' });
const line = (text: string, page = 1) => ({ BlockType: 'LINE', Text: text, Page: page });
const noWait = { sleep: async () => undefined };
const identity: DocumentReadIdentity = { jobId: 'fictional-job', documentId: 'fictional-document' };

describe('TextractReader', () => {
  it('reads images and one-page PDFs with the instant API', async () => {
    const { client, sent } = fakeClient(() => ({ Blocks: [line('Crown fee $1,000.00'), { BlockType: 'WORD', Text: 'Crown' }] }));
    expect(await new TextractReader(client, noWait).readLines('b', 'k', identity)).toEqual(['Crown fee $1,000.00']);
    expect(sent.map((s) => s.name)).toEqual(['DetectDocumentTextCommand']);
  });

  it('falls back to the asynchronous API for a multi-page PDF and keeps only the first pages', async () => {
    let polls = 0;
    const { client, sent } = fakeClient(({ name, input }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return { JobId: 'job-1' };
      if (!input.NextToken) {
        polls++;
        if (polls === 1) return { JobStatus: 'IN_PROGRESS' };
        return { JobStatus: 'SUCCEEDED', Blocks: [line('Page one: crown $1,000.00', 1), line('Page two: plan pays 50%', 2)], NextToken: 'more' };
      }
      return { JobStatus: 'SUCCEEDED', Blocks: [line('Page six: appendix', MAX_PDF_PAGES + 1)] };
    });
    const lines = await new TextractReader(client, noWait).readLines('b', 'k', identity);
    expect(lines).toEqual(['Page one: crown $1,000.00', 'Page two: plan pays 50%']);
    expect(sent.map((s) => s.name)).toEqual([
      'DetectDocumentTextCommand',
      'StartDocumentTextDetectionCommand',
      'GetDocumentTextDetectionCommand',
      'GetDocumentTextDetectionCommand',
      'GetDocumentTextDetectionCommand',
    ]);
  });

  it('gives up within its time budget instead of running past the worker timeout', async () => {
    let clock = 0;
    const { client } = fakeClient(({ name }) =>
      name === 'DetectDocumentTextCommand' ? unsupported : name === 'StartDocumentTextDetectionCommand' ? { JobId: 'j' } : { JobStatus: 'IN_PROGRESS' },
    );
    const reader = new TextractReader(client, { sleep: async () => void (clock += 1500), now: () => clock, maxWaitMs: 5000 });
    await expect(reader.readLines('b', 'k', identity)).rejects.toMatchObject({ name: 'TextractTimeout' });
  });

  it('passes through errors other than an unsupported format', async () => {
    const throttled = Object.assign(new Error('slow down'), { name: 'ThrottlingException' });
    const { client } = fakeClient(() => throttled);
    await expect(new TextractReader(client, noWait).readLines('b', 'k', identity)).rejects.toMatchObject({ name: 'ThrottlingException' });
  });

  it('uses the same opaque async start token across fresh readers for one job/document delivery', async () => {
    const started = new Map<string, string>();
    const { client, sent } = fakeClient(({ name, input }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') {
        const token = String(input.ClientRequestToken);
        if (!started.has(token)) started.set(token, `synthetic-textract-${started.size + 1}`);
        return { JobId: started.get(token) };
      }
      return { JobStatus: 'SUCCEEDED', Blocks: [line('Fictional document text')] };
    });
    for (let delivery = 0; delivery < 2; delivery++)
      await new TextractReader(client, noWait).readLines('synthetic-bucket', 'uploads/fictional-document.pdf', identity);
    const starts = sent.filter((call) => call.name === 'StartDocumentTextDetectionCommand');
    expect(starts).toHaveLength(2); // Two explicit deliveries, never an automatic retry.
    expect(starts[0]!.input).toEqual(starts[1]!.input);
    expect(starts[0]!.input.ClientRequestToken).toMatch(/^[a-f0-9]{64}$/);
    expect(started.size).toBe(1); // Mock implements AWS's documented token semantics.
    expect(sent.filter((call) => call.name === 'GetDocumentTextDetectionCommand').map((call) => call.input.JobId))
      .toEqual(['synthetic-textract-1', 'synthetic-textract-1']);
  });

  it('scopes async tokens to the application job, document and S3 location without plaintext identifiers', async () => {
    const { client, sent } = fakeClient(({ name }) => name === 'DetectDocumentTextCommand' ? unsupported
      : name === 'StartDocumentTextDetectionCommand' ? { JobId: 'synthetic-job' }
      : { JobStatus: 'SUCCEEDED', Blocks: [] });
    const inputs = [
      { bucket: 'synthetic-bucket', key: 'uploads/fictional-document.pdf', identity },
      { bucket: 'synthetic-bucket', key: 'uploads/fictional-document.pdf', identity: { ...identity, jobId: 'another-fictional-job' } },
      { bucket: 'synthetic-bucket', key: 'uploads/fictional-document.pdf', identity: { ...identity, documentId: 'another-fictional-document' } },
      { bucket: 'another-synthetic-bucket', key: 'uploads/fictional-document.pdf', identity },
      { bucket: 'synthetic-bucket', key: 'uploads/another-fictional-document.pdf', identity },
    ];
    for (const input of inputs) await new TextractReader(client, noWait).readLines(input.bucket, input.key, input.identity);
    const tokens = sent.filter((call) => call.name === 'StartDocumentTextDetectionCommand').map((call) => String(call.input.ClientRequestToken));
    expect(new Set(tokens).size).toBe(inputs.length);
    for (const token of tokens) {
      expect(token).toMatch(/^[a-f0-9]{64}$/);
      for (const input of inputs) for (const value of [input.identity.jobId, input.identity.documentId, input.bucket, input.key])
        expect(token).not.toContain(value);
    }
  });

  it.each([undefined, { jobId: '', documentId: 'fictional-document' }, { jobId: 'fictional-job', documentId: '' }])(
    'rejects missing stable identity before any paid command (%s)', async (invalid) => {
      const { client, sent } = fakeClient(() => { throw new Error('Paid dispatch must not occur'); });
      await expect(new TextractReader(client, noWait).readLines('b', 'k', invalid as DocumentReadIdentity))
        .rejects.toMatchObject({ name: 'DocumentReadIdentityError' });
      expect(sent).toEqual([]);
    },
  );

  it('propagates an uncertain async-start failure without retry or polling', async () => {
    const uncertain = Object.assign(new Error('Synthetic timeout'), { name: 'TimeoutError' });
    const { client, sent } = fakeClient(({ name }) => name === 'DetectDocumentTextCommand' ? unsupported : uncertain);
    await expect(new TextractReader(client, noWait).readLines('b', 'k', identity)).rejects.toBe(uncertain);
    expect(sent.map((call) => call.name)).toEqual(['DetectDocumentTextCommand', 'StartDocumentTextDetectionCommand']);
    expect(sent[1]!.input.ClientRequestToken).toMatch(/^[a-f0-9]{64}$/);
  });

  it('reads all remaining blocks on the fifth page before stopping at the next page', async () => {
    const { client, sent } = fakeClient(({ name, input }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return { JobId: 'fictional-textract-job' };
      if (!input.NextToken) return { JobStatus: 'SUCCEEDED', Blocks: [line('Fifth page beginning', 5)], NextToken: 'fifth-page-continuation' };
      if (input.NextToken === 'fifth-page-continuation')
        return { JobStatus: 'SUCCEEDED', Blocks: [line('Fifth page final amount $725.00', 5)], NextToken: 'sixth-page' };
      return { JobStatus: 'SUCCEEDED', Blocks: [line('Sixth page must be excluded', 6)], NextToken: 'do-not-fetch' };
    });
    expect(await new TextractReader(client, noWait).readLines('b', 'k', identity))
      .toEqual(['Fifth page beginning', 'Fifth page final amount $725.00']);
    expect(sent.filter((call) => call.name === 'GetDocumentTextDetectionCommand').map((call) => call.input.NextToken))
      .toEqual([undefined, 'fifth-page-continuation', 'sixth-page']);
  });

  it('stops pagination at the same time budget as polling without dispatching another read', async () => {
    let clock = 0;
    const { client, sent } = fakeClient(({ name }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return { JobId: 'fictional-textract-job' };
      clock += 1000;
      if (clock > 2000) throw new Error('Unexpected paid pagination dispatch');
      return { JobStatus: 'SUCCEEDED', Blocks: [line('Fictional page')], NextToken: `more-${clock}` };
    });
    const reader = new TextractReader(client, { sleep: async () => undefined, now: () => clock, maxWaitMs: 1000 });
    await expect(reader.readLines('b', 'k', identity)).rejects.toMatchObject({ name: 'TextractTimeout' });
    expect(sent.filter((call) => call.name === 'GetDocumentTextDetectionCommand')).toHaveLength(1);
  });

  it('does not issue a poll after sleeping through the remaining time budget', async () => {
    let clock = 0;
    const { client, sent } = fakeClient(({ name }) => name === 'DetectDocumentTextCommand' ? unsupported : { JobId: 'fictional-textract-job' });
    const reader = new TextractReader(client, { sleep: async () => void (clock += 1500), now: () => clock, maxWaitMs: 1000 });
    await expect(reader.readLines('b', 'k', identity)).rejects.toMatchObject({ name: 'TextractTimeout' });
    expect(sent.map((call) => call.name)).toEqual(['DetectDocumentTextCommand', 'StartDocumentTextDetectionCommand']);
  });

  it('rejects a repeated pagination token rather than looping or returning truncated text', async () => {
    let pages = 0;
    const { client, sent } = fakeClient(({ name }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return { JobId: 'fictional-textract-job' };
      if (++pages > 3) throw new Error('Unexpected paid pagination dispatch');
      return { JobStatus: 'SUCCEEDED', Blocks: [line('Fictional page')], NextToken: 'repeated-token' };
    });
    await expect(new TextractReader(client, noWait).readLines('b', 'k', identity))
      .rejects.toMatchObject({ name: 'TextractResponseError' });
    expect(sent.filter((call) => call.name === 'GetDocumentTextDetectionCommand')).toHaveLength(2);
  });

  it('rejects an asynchronous response with no job identifier before polling', async () => {
    const { client, sent } = fakeClient(({ name }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return {};
      throw new Error('Unexpected paid poll with no job identifier');
    });
    await expect(new TextractReader(client, noWait).readLines('b', 'k', identity))
      .rejects.toMatchObject({ name: 'TextractResponseError' });
    expect(sent.map((call) => call.name)).toEqual(['DetectDocumentTextCommand', 'StartDocumentTextDetectionCommand']);
  });

  it.each([false, true])('does not return a final batch received at the deadline (pagination=%s)', async (paginate) => {
    let clock = 0;
    const { client, sent } = fakeClient(({ name, input }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return { JobId: 'fictional-textract-job' };
      if (paginate && !input.NextToken) return { JobStatus: 'SUCCEEDED', Blocks: [line('Fictional beginning')], NextToken: 'final-page' };
      clock = 1000;
      return { JobStatus: 'SUCCEEDED', Blocks: [line('Late fictional result')] };
    });
    const reader = new TextractReader(client, { sleep: async () => undefined, now: () => clock, maxWaitMs: 1000 });
    await expect(reader.readLines('b', 'k', identity)).rejects.toMatchObject({ name: 'TextractTimeout' });
    expect(sent.filter((call) => call.name === 'GetDocumentTextDetectionCommand')).toHaveLength(paginate ? 2 : 1);
  });

  it('rejects an incomplete later result batch instead of returning a partial document', async () => {
    const { client, sent } = fakeClient(({ name, input }) => {
      if (name === 'DetectDocumentTextCommand') return unsupported;
      if (name === 'StartDocumentTextDetectionCommand') return { JobId: 'fictional-textract-job' };
      return input.NextToken ? { JobStatus: 'FAILED' }
        : { JobStatus: 'SUCCEEDED', Blocks: [line('Fictional beginning')], NextToken: 'failed-page' };
    });
    await expect(new TextractReader(client, noWait).readLines('b', 'k', identity))
      .rejects.toMatchObject({ name: 'TextractResponseError' });
    expect(sent.filter((call) => call.name === 'GetDocumentTextDetectionCommand')).toHaveLength(2);
  });
});
