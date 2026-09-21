import * as assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import * as vm from 'node:vm';
import { operatorWorkbenchHtml } from '../operator/OperatorWorkbenchHtml';

describe('0.7D2 read-only operator view markup', () => {
  it('renders the three distinct state sources and visual evidence sections', () => {
    const html = operatorWorkbenchHtml('safe-nonce');
    for (const label of [
      'Recorded lifecycle states', 'Security review and recovery',
      'Accepted Foundation Sec reasoning', 'Candidate and remediation',
      'Sandbox verification', 'Operator decision', 'Application and postcheck',
      'Application event timeline', 'Evidence artifact references',
    ]) {assert.ok(html.includes(label), label);}
    assert.ok(html.includes("message.run.contractVersion === '0.7D1'"));
    assert.ok(html.includes("'Not measured'"));
    const script = html.match(/<script nonce="safe-nonce">([\s\S]*?)<\/script>/)?.[1];
    assert.ok(script, 'inline Webview script must be present');
    assert.doesNotThrow(() => new vm.Script(script));
  });
  it('restricts the Webview with CSP and uses text nodes rather than HTML sinks', () => {
    const html = operatorWorkbenchHtml('safe-nonce');
    assert.ok(html.includes("default-src 'none'"));
    assert.ok(html.includes("script-src 'nonce-safe-nonce'"));
    assert.ok(html.includes("connect-src 'none'"));
    assert.ok(html.includes("node.textContent = String(value)"));
    assert.equal(html.includes('innerHTML'),false);
    assert.equal(html.includes('outerHTML'),false);
    assert.equal(html.includes('insertAdjacentHTML'),false);
    assert.equal(html.includes('type: \'decide\''),false);
    assert.equal(html.includes('type: \'apply\''),false);
  });
});
