import type { ScenarioComparison } from '@actionbridge/contracts';
import { z } from 'zod';
import type { AgentModel } from '../ports.js';

const SYSTEM = `Select one of the calculator's available scenarios for a short explanation.
Reply with exactly one JSON object: {"scenarioId": "an available scenario ID"}, or {"scenarioId": null} for the proposed dates.
Do not write prose, amounts, extra fields or tool calls. The application renders the explanation from the calculator's figures and assumptions.`;

const SelectionSchema = z.strictObject({ scenarioId: z.string().min(1).max(128).nullable() });

export function formatCents(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  return `${sign}$${Math.floor(abs / 100).toLocaleString('en-US')}.${String(abs % 100).padStart(2, '0')}`;
}

/**
 * The model may select a known scenario; it never supplies displayed prose or financial values.
 * Strict selection validation fails closed to the caller's existing calculator-summary fallback.
 * All wording, figures, financial roles and caveats below come from application-owned templates
 * and the actual engine result. Membership checks on free text cannot enforce those semantics.
 */
export async function explainComparison(model: AgentModel, comparison: ScenarioComparison): Promise<string | null> {
  const baseline = comparison.baseline.estimate.totals;
  const facts = {
    proposedDates: { scenarioId: comparison.baseline.scenarioId, youPayCents: baseline.patientPaysCents, planPaysCents: baseline.insurerPaysCents, conditional: comparison.baseline.conditional },
    alternatives: comparison.alternatives.map((a) => ({
      scenarioId: a.scenarioId,
      youPayCents: a.estimate.totals.patientPaysCents,
      lowerCostByCents: a.differenceFromBaselineCents,
      conditional: a.conditional,
    })),
    outcome: comparison.outcome,
  };

  const reply = await model.converse({ system: SYSTEM, messages: [{ role: 'user', content: [{ text: JSON.stringify(facts) }] }], tools: [], maxTokens: 300 });
  const block = reply.content[0];
  if (reply.stopReason !== 'end_turn' || reply.content.length !== 1 || !block || !('text' in block) || Object.keys(block).length !== 1 || typeof block.text !== 'string' || block.text.length > 500) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(block.text);
  } catch {
    return null;
  }
  const selection = SelectionSchema.safeParse(raw);
  if (!selection.success) return null;
  const id = selection.data.scenarioId;
  const alternative = comparison.alternatives.find((a) => a.scenarioId === id);
  if (id !== null && id !== comparison.baseline.scenarioId && !alternative) return null;

  const parts = [
    `For the proposed dates, the calculator estimates that you pay ${formatCents(baseline.patientPaysCents)} and the plan pays ${formatCents(baseline.insurerPaysCents)}.`,
  ];
  if (comparison.baseline.conditional) parts.push("The proposed-date estimate assumes next year's coverage stays the same.");
  if (alternative) {
    // The engine defines this as baseline patient cost minus alternative patient cost.
    const difference = alternative.differenceFromBaselineCents;
    const relation = difference > 0 ? `${formatCents(difference)} less than the proposed dates` : difference < 0 ? `${formatCents(-difference)} more than the proposed dates` : 'the same as the proposed dates';
    parts.push(`Within the dentist-supplied window, another evaluated schedule estimates that you pay ${formatCents(alternative.estimate.totals.patientPaysCents)} (${relation}).`);
    if (alternative.conditional) parts.push("The alternative estimate assumes next year's coverage stays the same.");
  }
  if (comparison.limitations.length > 0) parts.push("Review the calculator's limitations; some schedules could not be compared.");
  parts.push('These are estimates, not guaranteed payments; your dentist decides timing.');
  const rendered = parts.join(' ');
  return rendered.length <= 500 ? rendered : null;
}
