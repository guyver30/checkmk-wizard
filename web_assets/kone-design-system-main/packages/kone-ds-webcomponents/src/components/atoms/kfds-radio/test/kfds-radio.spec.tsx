import { newSpecPage } from '@stencil/core/testing';
import { KfdsRadio } from '../kfds-radio';

describe('kfds-radio', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsRadio],
      html: `<kfds-radio></kfds-radio>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-radio>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-radio>
    `);
  });
});
