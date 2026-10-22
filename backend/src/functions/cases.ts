import { caseRoutes } from '../features/cases/api/case-routes.js';
import { ledgerRoutes } from '../features/ledger/api/ledger-routes.js';
import { strategyRoutes } from '../features/strategies/api/strategy-routes.js';
import { planComparisonRoutes } from '../features/plan-comparisons/api/plan-comparison-routes.js';
import { composeHandler } from './compose.js';
import { dynamoServices } from './dynamo.js';

/** Case create/read/update, strategy saves and the case ledger: the API's writing Lambda. */
export const handler = composeHandler((config) => {
  const { cases, strategies, comparisons, ledger } = dynamoServices(config);
  const authMode = config.authMode;
  return {
    ...caseRoutes({ cases, authMode }),
    ...strategyRoutes({ strategies, authMode }),
    ...planComparisonRoutes({ comparisons, authMode }),
    ...ledgerRoutes({ cases, ledger, authMode }),
  };
});
