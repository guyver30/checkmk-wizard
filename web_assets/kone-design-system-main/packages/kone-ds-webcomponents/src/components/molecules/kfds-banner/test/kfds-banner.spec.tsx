import { newSpecPage } from '@stencil/core/testing';
import { KfdsBanner } from '../kfds-banner';

describe('kfds-banner', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsBanner],
      html: `<kfds-banner></kfds-banner>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-banner>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-banner>
    `);
  });
});
