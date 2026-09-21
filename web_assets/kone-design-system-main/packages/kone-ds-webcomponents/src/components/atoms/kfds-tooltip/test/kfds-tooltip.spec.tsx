import { newSpecPage } from '@stencil/core/testing';
import { KfdsTooltip } from '../kfds-tooltip';

describe('kfds-tooltip', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsTooltip],
      html: `<kfds-tooltip></kfds-tooltip>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-tooltip>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-tooltip>
    `);
  });
});
