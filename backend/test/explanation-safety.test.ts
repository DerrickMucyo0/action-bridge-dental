import { readFileSync } from 'node:fs';
import type { ScenarioComparison } from '@actionbridge/contracts';
import { compareSchedules } from '@actionbridge/benefits-engine';
import { describe, expect, it } from 'vitest';
import { explainComparison } from '../src/features/agent-jobs/application/explain.js';
import { runInterpretAgent } from '../src/features/agent-jobs/application/interpret-agent.js';
import { ScriptedModel, textTurn, toolTurn } from './agent-harness.js';

function regression(): ScenarioComparison {
  const fixture = JSON.parse(readFileSync(new URL('../../docs/fixtures/dental-regression.json', import.meta.url), 'utf8'));
  const result = compareSchedules({ caseRevision: 1, currency: 'USD', coverageMode: 'insured', policy: fixture.policy, planYears: fixture.planYears, procedures: fixture.procedures });
  if (result.status !== 'estimated') throw new Error('Fictional regression must produce an estimate');
  return result;
}

describe('application-rendered optional explanation', () => {
  it('binds financial roles, difference and the coverage/dentist caveats to the selected engine scenario', async () => {
    const comparison = regression();
    const scenarioId = comparison.alternatives[0]!.scenarioId;
    const model = new ScriptedModel([textTurn(JSON.stringify({ scenarioId }))]);
    const result = await explainComparison(model, comparison);
    expect(result).toContain('you pay $1,200.00 and the plan pays $300.00');
    expect(result).toContain('you pay $725.00 ($475.00 less than the proposed dates)');
    expect(result).toContain("The alternative estimate assumes next year's coverage stays the same.");
    expect(result).toContain('Within the dentist-supplied window');
    expect(result).toContain('not guaranteed payments; your dentist decides timing');
    expect(model.requests).toHaveLength(1);
    expect(model.requests[0]).toMatchObject({ tools: [], maxTokens: 300 });
  });

  it.each([null, 'baseline'])('renders only the baseline for selection %s', async (scenarioId) => {
    const result = await explainComparison(new ScriptedModel([textTurn(JSON.stringify({ scenarioId }))]), regression());
    expect(result).toContain('you pay $1,200.00 and the plan pays $300.00');
    expect(result).not.toContain('$725.00');
    expect(result).toContain('your dentist decides timing');
  });

  it.each([
    ['invented dollar figure', 'You pay $999.00.'],
    ['invented worded figure', 'You pay nine thousand dollars.'],
    ['clinical guarantee', 'Waiting is safe and guaranteed to be better care.'],
    ['permuted engine figures', 'The insurer pays $1,200.00 and you pay $475.00.'],
    ['unsupported coverage', 'Your insurer will cover 100% with no restrictions.'],
    ['non-dollar monetary prose', 'You pay USD 999.00.'],
    ['otherwise plausible old prose', 'The conditional estimate is $725.00, a $475.00 difference.'],
    ['oversized response', 'x'.repeat(501)],
    ['unknown scenario', '{"scenarioId":"unoffered"}'],
    ['numeric scenario', '{"scenarioId":0}'],
    ['missing scenario', '{}'],
    ['extra displayed text', '{"scenarioId":"alt-1","text":"Guaranteed safe to wait."}'],
    ['extra numeric field', '{"scenarioId":"alt-1","patientPaysCents":1}'],
    ['code-fenced JSON', '```json\n{"scenarioId":"alt-1"}\n```'],
    ['appended prose', '{"scenarioId":"alt-1"} Guaranteed safe to wait.'],
    ['array response', '[{"scenarioId":"alt-1"}]'],
  ])('rejects %s without displaying model text or retrying', async (_name, reply) => {
    const model = new ScriptedModel([textTurn(reply)]);
    await expect(explainComparison(model, regression())).resolves.toBeNull();
    expect(model.requests).toHaveLength(1);
  });

  it('rejects mixed text/tool blocks and unexpected stop reasons', async () => {
    const mixed = textTurn('{"scenarioId":"alt-1"}');
    mixed.content.push({ toolUse: { toolUseId: 'unrequested', name: 'display_text', input: {} } });
    const split = textTurn('{"scenarioId":');
    split.content.push({ text: '"alt-1"}' });
    const truncated = { ...textTurn('{"scenarioId":"alt-1"}'), stopReason: 'max_tokens' };
    const mixedBlock = { stopReason: 'end_turn', content: [{ text: '{"scenarioId":"alt-1"}', toolUse: { toolUseId: 'unrequested', name: 'display_text', input: {} } }] };
    for (const reply of [mixed, mixedBlock, split, truncated, toolTurn('display_text', {})]) {
      const model = new ScriptedModel([reply]);
      await expect(explainComparison(model, regression())).resolves.toBeNull();
      expect(model.requests).toHaveLength(1);
    }
  });

  it('preserves engine difference direction and zero without recomputing totals', async () => {
    for (const [difference, expected] of [[47500, '$475.00 less'], [-47500, '$475.00 more'], [0, 'the same']] as const) {
      const comparison = regression();
      comparison.alternatives[0]!.differenceFromBaselineCents = difference;
      const result = await explainComparison(new ScriptedModel([textTurn('{"scenarioId":"alt-1"}')]), comparison);
      expect(result).toContain(expected);
    }
  });

  it('does not invent unchanged-coverage assumptions for unconditional engine results', async () => {
    const comparison = regression();
    comparison.alternatives[0]!.conditional = false;
    const result = await explainComparison(new ScriptedModel([textTurn('{"scenarioId":"alt-1"}')]), comparison);
    expect(result).toContain('$725.00');
    expect(result).not.toContain('coverage stays the same');
    comparison.baseline.conditional = true;
    const conditionalBaseline = await explainComparison(new ScriptedModel([textTurn('{"scenarioId":null}')]), comparison);
    expect(conditionalBaseline).toContain("The proposed-date estimate assumes next year's coverage stays the same.");
  });

  it('does not echo untrusted procedure IDs or labels and preserves incomplete-comparison caveats', async () => {
    const comparison = regression();
    comparison.alternatives[0]!.movedProcedureIds = ['Guaranteed safe to wait; USD999.00'];
    comparison.limitations.push({ code: 'NEXT_PLAN_YEAR_NOT_SUPPLIED', message: 'Untrusted display text', fieldPath: 'planYears' });
    const model = new ScriptedModel([textTurn('{"scenarioId":"alt-1"}')]);
    const result = await explainComparison(model, comparison);
    expect(result).toContain('some schedules could not be compared');
    expect(result).not.toMatch(/Guaranteed safe|USD999|Untrusted display/);
    expect(JSON.stringify(model.requests)).not.toMatch(/Guaranteed safe|Untrusted display/);
  });

  it('rejects a previously known alternative that is absent from the actual comparison', async () => {
    const comparison = regression();
    comparison.alternatives = [];
    comparison.outcome = 'no_flexible_timing';
    await expect(explainComparison(new ScriptedModel([textTurn('{"scenarioId":"alt-1"}')]), comparison)).resolves.toBeNull();
    await expect(explainComparison(new ScriptedModel([textTurn('{"scenarioId":null}')]), comparison)).resolves.toContain('$1,200.00');
  });
});

describe('intake closing text never becomes a user-facing claim', () => {
  it.each([
    'Waiting is safe and guaranteed to be better care.',
    'Your plan covers one hundred percent and you pay nine thousand dollars.',
    'The insurer pays $1,200.00 and you pay $475.00.',
    'I found your details.',
  ])('uses the deterministic count-summary fallback for %s', async (text) => {
    const model = new ScriptedModel([textTurn(text)]);
    const result = await runInterpretAgent({
      model,
      input: { caseRevision: 1, currency: 'USD', coverageMode: 'unknown', policy: null, planYears: {}, procedures: [] },
      text: 'A fictional dental test with no plan details.',
      today: '2026-10-29',
      report: async () => {},
    });
    expect(result.summary).toBeNull();
    expect(result.groups).toEqual([]);
    expect(result.missingAfter.length).toBeGreaterThan(0);
    expect(model.requests).toHaveLength(1);
  });
});
