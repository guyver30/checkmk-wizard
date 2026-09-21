import { newSpecPage } from '@stencil/core/testing';
import { KfdsLoader } from '../kfds-loader';

describe('kfds-loader', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsLoader],
      html: `<kfds-loader></kfds-loader>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-loader>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-loader>
    `);
  });
});
