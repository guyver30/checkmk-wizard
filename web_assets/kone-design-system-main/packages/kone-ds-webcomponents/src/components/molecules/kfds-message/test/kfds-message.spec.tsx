import { newSpecPage } from '@stencil/core/testing';
import { KfdsMessage } from '../kfds-message';

describe('kfds-message', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsMessage],
      html: `<kfds-message></kfds-message>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-message>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-message>
    `);
  });
});
