export const usagePricing = {
  model: 'global.anthropic.claude-sonnet-4-6', inputPerMillion: 3, outputPerMillion: 15,
  checkedAt: '2026-10-31', source: 'https://aws.amazon.com/bedrock/pricing/',
};

const count = value => { const n = Number(value); return Number.isFinite(n) && n >= 0 ? n : 0; };
export function usageRow(row) {
  const calls = count(row.calls), input = count(row.input_tokens), output = count(row.output_tokens);
  const cacheRead = count(row.cache_read_input_tokens), cacheWrite = count(row.cache_write_input_tokens);
  const total = input + output;
  // Cache write TTL and other model prices are not present in this summary.
  // Do not silently charge an unverified rate for them.
  const estimatedCost = row.model_id === usagePricing.model && cacheRead === 0 && cacheWrite === 0
    ? (input * usagePricing.inputPerMillion + output * usagePricing.outputPerMillion) / 1_000_000 : null;
  return { ...row, calls, input, output, cacheRead, cacheWrite, total,
    averageInput: calls ? input / calls : null, averageOutput: calls ? output / calls : null,
    averageTokens: calls ? total / calls : null, estimatedCost,
    averageCost: calls && estimatedCost !== null ? estimatedCost / calls : null };
}

export function summarizeUsage(rows = []) {
  const values = rows.map(usageRow);
  const result = values.reduce((a,r) => ({ calls:a.calls+r.calls, input:a.input+r.input,
    output:a.output+r.output, total:a.total+r.total, cacheRead:a.cacheRead+r.cacheRead,
    cacheWrite:a.cacheWrite+r.cacheWrite, succeeded:a.succeeded+(r.status==='succeeded'?r.calls:0),
    failed:a.failed+(r.status==='failed'||r.status==='timed_out'?r.calls:0),
    estimatedCost:a.estimatedCost===null||r.estimatedCost===null?null:a.estimatedCost+r.estimatedCost }),
  {calls:0,input:0,output:0,total:0,cacheRead:0,cacheWrite:0,succeeded:0,failed:0,estimatedCost:0});
  return {...result,averageTokens:result.calls?result.total/result.calls:null,
    averageCost:result.calls&&result.estimatedCost!==null?result.estimatedCost/result.calls:null,rows:values};
}
